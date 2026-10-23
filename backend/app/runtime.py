"""Explicit file-based configuration and management for native Linux deployments."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import stat
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import MigrationSettings, Settings

BACKEND = Path(__file__).resolve().parents[1]


class ConfigurationError(Exception):
    pass


def load_configuration(path: Path, *, migration=False, development=False):
    """Do not import .env or application settings from the operator's terminal."""
    if not path.is_file():
        raise ConfigurationError("No existe el archivo de configuracion indicado.")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o007:
        raise ConfigurationError(
            "El archivo de secretos no debe ser accesible para otros usuarios."
        )
    values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    model = MigrationSettings if migration else Settings
    known = set(model.model_fields)
    normalized = {key.lower(): value for key, value in values.items() if value is not None}
    unexpected = normalized.keys() - known
    if unexpected:
        raise ConfigurationError("Opciones desconocidas: " + ", ".join(sorted(unexpected)))
    # Blank optional entries should not turn into invalid URLs, UUIDs or CA paths.
    normalized = {key: value for key, value in normalized.items() if value != ""}
    for key in (
        "allowed_origins",
        "allowed_hosts",
        "entra_allowed_client_ids",
        "company_codes",
        "business_units",
        "trusted_proxy_ips",
    ):
        if key in normalized:
            try:
                normalized[key] = json.loads(normalized[key])
            except ValueError:
                raise ConfigurationError(f"JSON invalido en {key.upper()}.") from None
    environment = os.environ.copy()
    try:
        for key in list(os.environ):
            if (
                key.lower() in Settings.model_fields
                or key.lower() in MigrationSettings.model_fields
            ):
                os.environ.pop(key)
        settings = model(_env_file=None, **normalized)
    finally:
        os.environ.clear()
        os.environ.update(environment)
    if not development and settings.app_env != "production":
        raise ConfigurationError("El despliegue Linux requiere APP_ENV=production.")
    url = make_url((settings.migration_database_url or settings.database_url).get_secret_value())
    if not url.host or not url.database or not url.username:
        raise ConfigurationError("La conexion debe indicar host, base de datos y usuario.")
    if url.host.endswith(".invalid") or url.password in {None, "", "CHANGE_ME", "PASSWORD"}:
        raise ConfigurationError(
            "Completa el endpoint y la contrasena PostgreSQL proporcionados por TI."
        )
    if settings.app_env == "production":
        ca = url.query.get("sslrootcert")
        if not isinstance(ca, str) or not Path(ca).is_absolute() or not Path(ca).is_file():
            raise ConfigurationError(
                "Configura sslrootcert con el archivo CA de PostgreSQL legible."
            )
        ssl.create_default_context().load_verify_locations(cafile=ca)
        if not migration:
            if "127.0.0.1" not in settings.trusted_proxy_ips:
                raise ConfigurationError(
                    "El perfil Linux requiere el proxy local 127.0.0.1 en TRUSTED_PROXY_IPS."
                )
            if settings.entra_ca_bundle and (
                not Path(settings.entra_ca_bundle).is_absolute()
                or not Path(settings.entra_ca_bundle).is_file()
            ):
                raise ConfigurationError("No se puede leer ENTRA_CA_BUNDLE.")
            if settings.entra_ca_bundle:
                ssl.create_default_context().load_verify_locations(cafile=settings.entra_ca_bundle)
    return settings


def check_database(settings, *, migration=False, connection_only=False):
    """Read-only validation; no schema creation, upgrades or operational writes."""
    url = (settings.migration_database_url or settings.database_url).get_secret_value()
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            identity = connection.execute(text("SELECT current_user, current_database()")).one()
            expected = make_url(url).username
            if identity[0] != expected:
                raise ConfigurationError(
                    "La identidad efectiva de PostgreSQL no coincide con la configurada."
                )
            if settings.app_env == "production":
                if not connection.scalar(
                    text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
                ):
                    raise ConfigurationError("PostgreSQL no reporta TLS para esta sesion.")
            if not migration:
                if settings.app_env == "production":
                    privileged = connection.execute(
                        text(
                            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                            "FROM pg_roles WHERE rolname=current_user"
                        )
                    ).one()
                    if any(privileged):
                        raise ConfigurationError(
                            "El rol de la API tiene privilegios administrativos."
                        )
                if not connection_only:
                    heads = set(ScriptDirectory(str(BACKEND / "migrations")).get_heads())
                    actual = set(
                        connection.scalars(text("SELECT version_num FROM alembic_version"))
                    )
                    if actual != heads:
                        raise ConfigurationError("Las migraciones no corresponden a esta version.")
    finally:
        engine.dispose()


def check_pair(api, migration):
    first = make_url(api.database_url.get_secret_value())
    second = make_url(
        (migration.migration_database_url or migration.database_url).get_secret_value()
    )
    if (first.host.lower(), first.port or 5432, first.database) != (
        second.host.lower(),
        second.port or 5432,
        second.database,
    ):
        raise ConfigurationError("API y migraciones deben usar el mismo endpoint, puerto y base.")


def probe(settings, port, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health/ready",
        headers={
            "Host": urlsplit(settings.allowed_origins[0]).netloc,
            "X-Forwarded-Proto": "https",
        },
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(request, timeout=3) as response:
                if (
                    response.url == request.full_url
                    and json.load(response).get("status") == "ready"
                ):
                    print("API lista; PostgreSQL y migraciones disponibles.")
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise ConfigurationError("La API no quedo lista. Revisa journalctl y la conexion PostgreSQL.")


def serve(settings: Settings, *, port=8000):
    import uvicorn

    from app.main import create_app

    # Serving uses only the validated object, with no inherited database/migration
    # identity left in the API process environment.
    for key in list(os.environ):
        if key.lower() in Settings.model_fields or key.lower() in MigrationSettings.model_fields:
            os.environ.pop(key)
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxy_ips,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=25,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "serve", "probe", "migrate", "bootstrap-admin"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--migration", action="store_true", help="Revisar la configuracion del DBA."
    )
    parser.add_argument(
        "--database", action="store_true", help="Comprobar PostgreSQL sin modificar datos."
    )
    parser.add_argument(
        "--connection-only", action="store_true", help="Comprobar conexion antes de migrar."
    )
    parser.add_argument(
        "--migration-env-file",
        type=Path,
        help="Comprobar que los dos roles apuntan a la misma base.",
    )
    parser.add_argument(
        "--development", action="store_true", help="Solo check de configuracion local."
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--object-id", type=UUID)
    parser.add_argument("--email")
    parser.add_argument("--display-name")
    parser.add_argument("--analyst-code", type=int)
    parser.add_argument("--last-reference-sequence", type=int, default=0)
    args = parser.parse_args(argv)
    if args.development and args.action != "check":
        parser.error("--development solo se admite para check")
    if args.migration and args.action not in {"check", "migrate", "bootstrap-admin"}:
        parser.error("La API no admite credenciales de migracion")
    if args.migration_env_file and (args.action != "check" or args.migration):
        parser.error("La comprobacion de las dos conexiones solo se admite en check de API")
    if not 1 <= args.timeout <= 600 or not 1024 <= args.port <= 65535:
        parser.error("Puerto o tiempo de espera fuera del rango admitido")
    try:
        migration = args.migration or args.action in {"migrate", "bootstrap-admin"}
        settings = load_configuration(
            args.env_file, migration=migration, development=args.development
        )
        if args.migration_env_file:
            job = load_configuration(args.migration_env_file, migration=True)
            check_pair(settings, job)
        if args.action == "check":
            if args.database:
                check_database(settings, migration=migration, connection_only=args.connection_only)
            print(
                json.dumps(
                    {
                        "configuration": "ok",
                        "mode": settings.app_env,
                        "database": "ok" if args.database else "not_checked",
                    }
                )
            )
        elif args.action == "serve":
            serve(settings, port=args.port)
        elif args.action == "probe":
            probe(settings, args.port, args.timeout)
        elif args.action == "migrate":
            config = Config(str(BACKEND / "alembic.ini"))
            config.attributes["migration_settings"] = settings
            command.upgrade(config, "head")
            print("Migraciones aplicadas.")
        else:
            from app.cli import bootstrap_admin

            if not all((args.object_id, args.email, args.display_name)):
                raise ConfigurationError(
                    "Indica object-id, email y display-name del administrador aprobado."
                )
            bootstrap_admin(
                settings,
                args.object_id,
                args.email,
                args.display_name,
                args.analyst_code,
                args.last_reference_sequence,
            )
            print("Administrador inicial aprovisionado.")
        return 0
    except ValidationError as error:
        fields = sorted(
            {
                str(item["loc"][0]) if item["loc"] else "configuracion"
                for item in error.errors(include_input=False, include_context=False)
            }
        )
        print("ERROR: revisa " + ", ".join(fields) + ". No se muestran valores de secretos.")
    except ConfigurationError as error:
        print(f"ERROR: {error}")
    except Exception:
        # Drivers and TLS libraries can include credentials in exception messages.
        print(
            "ERROR: no se completo la operacion. Revisa conectividad, certificados, permisos y esquema con TI/DBA."
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
