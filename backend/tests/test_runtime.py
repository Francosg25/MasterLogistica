import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import runtime
from app.main import create_app


@pytest.fixture
def production_file(tmp_path, settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test deployment CA")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    ca = tmp_path / "ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": f"postgresql+psycopg://masterlogistica_app:private-test-password@localhost:1/masterlogistica_test?sslmode=verify-full&sslrootcert={ca.as_posix()}",
        "ENTRA_TENANT_ID": str(settings.entra_tenant_id),
        "ENTRA_API_CLIENT_ID": str(settings.entra_api_client_id),
        "ENTRA_FRONTEND_CLIENT_ID": str(settings.entra_frontend_client_id),
        "ENTRA_ALLOWED_CLIENT_IDS": json.dumps([str(settings.entra_frontend_client_id)]),
        "ALLOWED_HOSTS": '["logistica.test"]',
        "ALLOWED_ORIGINS": '["https://logistica.test"]',
        "ENFORCE_HTTPS": "true",
        "BUSINESS_UNITS": '{"M01":"Test unit"}',
        "TRUSTED_PROXY_IPS": '["127.0.0.1"]',
        "ENTRA_CA_BUNDLE": ca.as_posix(),
    }
    file = tmp_path / "api.env"

    def write(changes=None):
        current = {**values, **(changes or {})}
        file.write_text("\n".join(f"{key}={value}" for key, value in current.items()) + "\n")
        file.chmod(0o600)
        return file

    return values, write


def test_explicit_file_ignores_foreign_database_and_migration_environment(
    production_file, monkeypatch
):
    values, write = production_file
    monkeypatch.setenv("DATABASE_URL", "mysql://wrong-terminal:foreign-secret@wrong/db")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://admin:foreign@wrong/db")
    result = runtime.load_configuration(write())
    assert result.database_url.get_secret_value() == values["DATABASE_URL"]
    assert result.migration_database_url is None
    assert os.environ["DATABASE_URL"].startswith("mysql://")


def test_unknown_options_and_invalid_json_do_not_print_values(production_file, capsys):
    _, write = production_file
    file = write({"BUSINESS_UNITS": "private-sensitive-invalid-json"})
    assert runtime.main(["check", "--env-file", str(file)]) == 1
    assert "private-sensitive" not in capsys.readouterr().out
    file = write({"TYPO_DATABASE_URL": "private-test-password"})
    assert runtime.main(["check", "--env-file", str(file)]) == 1
    output = capsys.readouterr().out
    assert "typo_database_url" in output and "private-test-password" not in output


@pytest.mark.parametrize(
    "changes",
    [
        {"ENTRA_FRONTEND_CLIENT_ID": ""},
        {"ALLOWED_ORIGINS": "[]"},
        {"TRUSTED_PROXY_IPS": '["*"]'},
        {"TRUSTED_PROXY_IPS": '["0.0.0.0/0"]'},
        {"TRUSTED_PROXY_IPS": "[]"},
        {"APP_ENV": "development"},
    ],
)
def test_incomplete_production_configuration_fails_closed(production_file, changes, capsys):
    _, write = production_file
    assert runtime.main(["check", "--env-file", str(write(changes))]) == 1
    assert "private-test-password" not in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_world_readable_secret_file_is_rejected(production_file):
    _, write = production_file
    file = write()
    file.chmod(0o644)
    with pytest.raises(runtime.ConfigurationError, match="otros usuarios"):
        runtime.load_configuration(file)


def test_two_roles_must_point_to_same_database_before_migration(production_file):
    values, write = production_file
    api = runtime.load_configuration(write())
    job = runtime.MigrationSettings(
        _env_file=None,
        app_env="production",
        database_url=values["DATABASE_URL"].replace("masterlogistica_app:", "migration:"),
    )
    runtime.check_pair(api, job)
    other = job.model_copy(
        update={
            "database_url": runtime.MigrationSettings(
                _env_file=None,
                app_env="production",
                database_url=job.database_url.get_secret_value().replace(
                    "masterlogistica_test?", "other_database?"
                ),
            ).database_url
        }
    )
    with pytest.raises(runtime.ConfigurationError, match="mismo endpoint"):
        runtime.check_pair(api, other)


def test_only_trusted_proxy_can_supply_https_and_auth_is_still_required(production_file):
    _, write = production_file
    settings = runtime.load_configuration(write())
    app = ProxyHeadersMiddleware(create_app(settings), trusted_hosts=settings.trusted_proxy_ips)
    with TestClient(
        app, base_url="http://logistica.test", client=("127.0.0.1", 54000), follow_redirects=False
    ) as client:
        assert client.get("/health/live", headers={"X-Forwarded-Proto": "https"}).status_code == 200
        assert (
            client.get("/api/v1/auth/config", headers={"X-Forwarded-Proto": "https"}).json()[
                "enabled"
            ]
            is True
        )
        assert (
            client.get("/api/v1/auth/me", headers={"X-Forwarded-Proto": "https"}).status_code == 401
        )
        assert client.get("/health/live").status_code == 307
        assert (
            client.get(
                "/health/live", headers={"Host": "wrong.test", "X-Forwarded-Proto": "https"}
            ).status_code
            == 400
        )
    with TestClient(
        app,
        base_url="http://logistica.test",
        client=("198.51.100.8", 54000),
        follow_redirects=False,
    ) as client:
        assert client.get("/health/live", headers={"X-Forwarded-Proto": "https"}).status_code == 307


def test_runtime_binds_loopback_and_uses_exact_trusted_proxy_list(production_file, monkeypatch):
    _, write = production_file
    settings = runtime.load_configuration(write())
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "foreign-migration-secret")
    with patch("uvicorn.run") as run:
        runtime.serve(settings)
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["proxy_headers"] is True
    assert run.call_args.kwargs["forwarded_allow_ips"] == ["127.0.0.1"]
    assert run.call_args.kwargs["access_log"] is False
    assert "MIGRATION_DATABASE_URL" not in os.environ


def test_corporate_ca_extends_tls_validation_without_disabling_it(production_file):
    _, write = production_file
    app = create_app(runtime.load_configuration(write()))
    context = app.state.token_validator.jwks.ssl_context
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_migration_receives_only_the_explicit_job_configuration(production_file, tmp_path):
    values, _ = production_file
    job = tmp_path / "migration.env"
    url = values["DATABASE_URL"].replace("masterlogistica_app:", "migration:")
    job.write_text(f"APP_ENV=production\nDATABASE_URL={url}\n")
    job.chmod(0o600)
    with patch.object(runtime.command, "upgrade") as upgrade:
        assert runtime.main(["migrate", "--env-file", str(job)]) == 0
    config, head = upgrade.call_args.args
    assert head == "head"
    assert isinstance(config.attributes["migration_settings"], runtime.MigrationSettings)
    assert config.attributes["migration_settings"].database_url.get_secret_value() == url


@pytest.mark.parametrize("failure", [None, "identity", "tls", "privileges", "schema"])
def test_database_preflight_rejects_wrong_identity_tls_privileges_and_schema(
    production_file, failure
):
    _, write = production_file
    settings = runtime.load_configuration(write())
    queries = []
    expected_heads = set(runtime.ScriptDirectory(str(runtime.BACKEND / "migrations")).get_heads())

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            query = str(statement)
            queries.append(query)
            if "current_database()" in query:
                return SimpleNamespace(
                    one=lambda: (
                        "wrong" if failure == "identity" else "masterlogistica_app",
                        "masterlogistica_test",
                    )
                )
            return SimpleNamespace(one=lambda: (failure == "privileges", False, False, False))

        def scalar(self, statement):
            queries.append(str(statement))
            return failure != "tls"

        def scalars(self, statement):
            queries.append(str(statement))
            return ["old_schema"] if failure == "schema" else expected_heads

    disposed = []
    engine = SimpleNamespace(connect=Connection, dispose=lambda: disposed.append(True))
    with patch.object(runtime, "create_engine", return_value=engine):
        if failure:
            with pytest.raises(runtime.ConfigurationError):
                runtime.check_database(settings)
        else:
            runtime.check_database(settings)
    assert disposed == [True]
    assert queries and all(query.startswith("SELECT ") for query in queries)
