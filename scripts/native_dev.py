"""Local Python/Angular launcher; no Docker or virtual machine is required."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from local_dev import (
    ROOT,
    URL,
    Launcher,
    LocalError,
    checkout_lock,
    frontend_dependencies_current,
    port_busy,
    read_json,
)

CONTROL_PORT = 8317


def selected_database(args):
    value = getattr(args, "database", None)
    if value is None:
        return None
    if not value.strip() or "://" in value or any(char in value for char in "?#"):
        raise LocalError("--database debe indicar un archivo SQLite local.")
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        raise LocalError("--database debe indicar un archivo, no una carpeta.")
    return path


def backend_install_command(python, lock, *, windows):
    command = [str(python), "-m", "pip", "install", "--require-hashes"]
    if windows:
        # SQLAlchemy supports pure Python; corporate Windows may reject its optional .pyd files.
        command.extend(["--no-binary=sqlalchemy", "--no-cache-dir"])
    return command + ["-r", str(lock)]


def json_response(handler, status, value):
    body = json.dumps(value).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class DemoHandler(BaseHTTPRequestHandler):
    """An isolated access configuration for the existing read-only UI demo."""

    def do_GET(self):
        if self.path == "/api/v1/auth/config":
            json_response(
                self,
                200,
                {
                    "enabled": False,
                    "authority": None,
                    "frontend_client_id": None,
                    "scope": None,
                },
            )
        elif self.path in {"/health/ready", "/health/live"}:
            json_response(self, 200, {"status": "ready", "mode": "demo"})
        else:
            json_response(self, 404, {"detail": "Demostracion local de solo lectura"})

    def do_POST(self):
        json_response(self, 403, {"detail": "La demostracion no permite guardar datos"})

    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, *args):
        pass


def control_request(state_path, action):
    data = read_json(state_path)
    token = data.get("token")
    if not isinstance(token, str) or len(token) < 32:
        return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"http://127.0.0.1:{CONTROL_PORT}/{action}",
        headers={"X-Local-Control": token},
        method="POST" if action == "stop" else "GET",
    )
    try:
        with opener.open(request, timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


class Native:
    def __init__(self, root=ROOT):
        self.core = Launcher(root)
        self.core.load_secrets(self.core.root / ".env.native")
        self.root = self.core.root
        self.state = self.core.data / "native.json"
        self.children = []
        self.files = []
        self.servers = []
        self.stop = threading.Event()
        self.token = secrets.token_urlsafe(32)
        self.mode = "database"
        self.is_ready = False
        self.database_path = None

    def frontend(self, args):
        node = shutil.which("node")
        if not node:
            raise LocalError(
                "No se encontro Node. Usa la instalacion autorizada compatible con Angular 21."
            )
        _, version = self.core.run([node, "-p", "process.versions.node"])
        try:
            major, minor, _ = (int(part) for part in version.strip().split(".", 2))
        except ValueError:
            raise LocalError("No se pudo comprobar la version de Node.") from None
        if not (
            (major == 20 and minor >= 19)
            or (major == 22 and minor >= 12)
            or major == 24
        ):
            raise LocalError(
                "Angular 21 requiere Node 20.19+, 22.12+ o 24.x. Usa la version autorizada por TI."
            )
        cli = self.root / "frontend/node_modules/@angular/cli/bin/ng.js"
        installed = self.core.data / "native-frontend.json"
        lock = self.root / "frontend/package-lock.json"
        import hashlib

        digest = hashlib.sha256(lock.read_bytes()).hexdigest()
        install = (
            args.install
            or not cli.exists()
            or not frontend_dependencies_current(self.root)
        )
        if install and args.skip_install:
            raise LocalError(
                "Faltan dependencias o cambio el lock. Reintenta sin --skip-install."
            )
        if install:
            candidates = [Path(node).parent / "node_modules/npm/bin/npm-cli.js"]
            command = shutil.which("npm.cmd" if os.name == "nt" else "npm")
            if command:
                resolved = Path(command).resolve()
                # Unix distributions often symlink npm directly to npm-cli.js.
                if resolved.suffix == ".js":
                    candidates.append(resolved)
                candidates.append(resolved.parent / "node_modules/npm/bin/npm-cli.js")
            candidates.append(
                Path(node).resolve().parent.parent
                / "lib/node_modules/npm/bin/npm-cli.js"
            )
            npm = next((path for path in candidates if path.is_file()), None)
            if npm is None:
                raise LocalError(
                    "No se encontro npm-cli.js junto a Node. Revisa la instalacion autorizada."
                )
            self.core.say("Preparando dependencias de Angular...")
            self.core.run(
                [node, str(npm), "ci", "--prefix", str(self.root / "frontend")],
                stream=True,
            )
        installed.write_text(json.dumps({"lock": digest}), encoding="utf-8")
        self.core.run(
            [node, str(self.root / "frontend/scripts/check-toolchain.cjs")], stream=True
        )
        return [
            node,
            str(cli),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "4200",
            "--proxy-config",
            "proxy.conf.json",
        ]

    def backend(self, args):
        python = (
            Path(args.python)
            if args.python
            else self.root
            / ".venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if not python.exists():
            if args.python or args.skip_install:
                raise LocalError(
                    "No existe el interprete Python indicado o falta .venv."
                )
            self.core.run(
                [sys.executable, "-m", "venv", str(self.root / ".venv")], stream=True
            )
        marker = self.core.data / "native-python.json"
        import hashlib

        digest = hashlib.sha256(
            (self.root / "backend/requirements.lock").read_bytes()
        ).hexdigest()
        saved = read_json(marker)
        if (
            args.install
            or saved.get("lock") != digest
            or saved.get("python") != str(python)
        ):
            if args.skip_install:
                self.core.run(
                    [str(python), "-c", "import fastapi,psycopg,alembic,dotenv,uvicorn"]
                )
            else:
                self.core.say(
                    "Preparando dependencias Python con el lock del backend..."
                )
                previous = self.core.env.get("DISABLE_SQLALCHEMY_CEXT")
                windows = sys.platform == "win32"
                if windows:
                    self.core.env["DISABLE_SQLALCHEMY_CEXT"] = "1"
                try:
                    self.core.run(
                        backend_install_command(
                            python,
                            self.root / "backend/requirements.lock",
                            windows=windows,
                        ),
                        stream=True,
                    )
                finally:
                    if previous is None:
                        self.core.env.pop("DISABLE_SQLALCHEMY_CEXT", None)
                    else:
                        self.core.env["DISABLE_SQLALCHEMY_CEXT"] = previous
            marker.write_text(
                json.dumps({"lock": digest, "python": str(python)}), encoding="utf-8"
            )
        self.database_path = selected_database(args)
        if self.database_path is not None:
            # A separate SQLite session never reads a corporate .env.native connection.
            values = {"DATABASE_URL": "sqlite+pysqlite:///" + str(self.database_path)}
            self.core.say("Base local independiente: " + str(self.database_path))
        else:
            env_file = self.root / ".env.native"
            _, raw = self.core.run(
                [
                    str(python),
                    "-c",
                    (
                        "import json,sys; from dotenv import dotenv_values; "
                        "print(json.dumps(dotenv_values(sys.argv[1], interpolate=False)))"
                    ),
                    str(env_file),
                ]
            )
            values = {
                key: value
                for key, value in json.loads(raw).items()
                if value not in (None, "")
            }
        if values.get("APP_ENV", "development") != "development":
            raise LocalError(
                "El lanzador nativo solo admite APP_ENV=development en .env.native."
            )
        database = values.get("DATABASE_URL", "")
        if database and not database.startswith(
            ("postgresql+psycopg://", "sqlite+pysqlite:///")
        ):
            raise LocalError(
                "DATABASE_URL debe usar SQLite local o PostgreSQL con psycopg."
            )
        self.core.secrets.extend(
            value
            for key, value in values.items()
            if "PASSWORD" in key or key.endswith("DATABASE_URL")
        )
        # Never inherit a production connection or migration identity from the terminal.
        protected = {
            "DATABASE_URL",
            "MIGRATION_DATABASE_URL",
            "APP_ENV",
            "AUTH_MODE",
            "ENTRA_TENANT_ID",
            "ENTRA_API_CLIENT_ID",
            "ENTRA_FRONTEND_CLIENT_ID",
            "ENTRA_ALLOWED_CLIENT_IDS",
            "ENTRA_REQUIRED_SCOPE",
            "ENTRA_CA_BUNDLE",
            "TRUSTED_PROXY_IPS",
            "COMPANY_CODES",
            "BUSINESS_UNITS",
            "ENFORCE_HTTPS",
            "ALLOWED_HOSTS",
            "ALLOWED_ORIGINS",
            "JWT_LEEWAY_SECONDS",
        }
        for key in list(self.core.env):
            if key.upper() in protected:
                self.core.env.pop(key)
        self.core.env.update(values)
        self.core.env.update(
            {
                "APP_ENV": "development",
                "ENFORCE_HTTPS": "false",
                "ALLOWED_HOSTS": '["127.0.0.1","localhost"]',
                "ALLOWED_ORIGINS": '["http://127.0.0.1:4200","http://localhost:4200"]',
            }
        )
        self.core.env["PYTHONPATH"] = str(self.root / "backend")
        local = not database or database.startswith("sqlite+pysqlite:///")
        if local:
            if (
                values.get("MIGRATION_DATABASE_URL")
                or values.get("AUTH_MODE", "development") != "development"
            ):
                raise LocalError(
                    "SQLite local usa AUTH_MODE=development y no lleva credenciales de migracion."
                )
            self.core.env["AUTH_MODE"] = "development"
            self.core.say(
                "Base SQLite local persistente; se prepara automaticamente al iniciar la API."
            )
        elif values.get("MIGRATION_DATABASE_URL"):
            self.core.say(
                "Aplicando migraciones a la base de desarrollo configurada..."
            )
            self.core.run(
                [
                    str(python),
                    "-m",
                    "alembic",
                    "-c",
                    str(self.root / "backend/alembic.ini"),
                    "upgrade",
                    "head",
                ],
                stream=True,
            )
        else:
            self.core.say(
                "Sin credenciales de migracion; se usara el esquema ya preparado por el DBA."
            )
        # The long-running API must not receive the migration credentials.
        self.core.env.pop("MIGRATION_DATABASE_URL", None)
        return [
            str(python),
            "-c",
            (
                "import uvicorn; from app.config import Settings; from app.main import create_app; "
                "uvicorn.run(create_app(Settings(_env_file=None)), host='127.0.0.1', "
                "port=8000, proxy_headers=False)"
            ),
        ]

    def spawn(self, name, command, cwd):
        output = (self.core.data / f"{name}.log").open("w", encoding="utf-8")
        self.files.append(output)
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=self.core.env,
            stdout=output,
            stderr=subprocess.STDOUT,
            **options,
        )
        self.children.append((name, process))

    def server(self, port, handler):
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))

    def control_handler(self):
        owner = self

        class Control(BaseHTTPRequestHandler):
            def handle_action(self):
                if not secrets.compare_digest(
                    self.headers.get("X-Local-Control", ""), owner.token
                ):
                    json_response(self, 403, {"detail": "No autorizado"})
                elif self.command == "GET" and self.path == "/status":
                    json_response(
                        self,
                        200,
                        {
                            "mode": owner.mode,
                            "ready": owner.is_ready,
                            **(
                                {"database": str(owner.database_path)}
                                if owner.database_path
                                else {}
                            ),
                        },
                    )
                elif self.command == "POST" and self.path == "/stop":
                    json_response(self, 200, {"stopping": True})
                    owner.stop.set()
                else:
                    json_response(self, 404, {"detail": "No disponible"})

            do_GET = handle_action
            do_POST = handle_action

            def log_message(self, *args):
                pass

        return Control

    def start(self, args):
        database = selected_database(args)
        current = control_request(self.state, "status")
        if current:
            if current.get("database") != (str(database) if database else None):
                raise LocalError(
                    "Hay una sesion local con otra base. Usa DETENER_LOCAL.cmd antes de cambiar de sesion."
                )
            self.core.say(f"La sesion local ya esta activa ({current['mode']}).")
            if not args.no_browser:
                webbrowser.open(URL)
            return
        with checkout_lock(self.core.data / "native-start.lock"):
            for port in (8000, 4200, CONTROL_PORT):
                if port_busy(port):
                    raise LocalError(
                        f"El puerto {port} esta ocupado. Deten tu sesion anterior con Ctrl+C; no se cerraran procesos ajenos."
                    )
            self.mode = "demo" if args.demo else "database"
            self.core.say(f"Inicio directo sin Docker. Modo: {self.mode}.")
            if self.mode == "demo":
                self.core.say(
                    "Demostracion opcional. Inicia sin --demo para crear y guardar datos en SQLite local."
                )
            angular = self.frontend(args)
            api = self.backend(args) if self.mode == "database" else None
            self.server(CONTROL_PORT, self.control_handler())
            self.state.write_text(json.dumps({"token": self.token}), encoding="utf-8")
            self.state.chmod(0o600)
            if api:
                self.spawn("api", api, self.root / "backend")
            else:
                self.server(8000, DemoHandler)
            self.spawn("frontend", angular, self.root / "frontend")
            deadline = time.monotonic() + args.timeout
            while not self.stop.is_set():
                for name, process in self.children:
                    if process.poll() is not None:
                        raise LocalError(
                            f"El proceso {name} termino. Revisa .local-dev/{name}.log; no se modificaron politicas del equipo."
                        )
                if not self.is_ready and self.core.ready():
                    self.is_ready = True
                    self.core.say(f"MasterLogistica listo: {URL}")
                    self.core.say(
                        "Conserva esta ventana abierta. Para detener: Ctrl+C o DETENER_LOCAL.cmd."
                    )
                    if not args.no_browser:
                        webbrowser.open(URL)
                if not self.is_ready and time.monotonic() > deadline:
                    raise LocalError(
                        "No termino el arranque. Revisa VER_LOGS.cmd para identificar el proceso que fallo."
                    )
                self.stop.wait(0.5)

    def stop_session(self):
        result = control_request(self.state, "stop")
        if result:
            deadline = time.monotonic() + 15
            while control_request(self.state, "status"):
                if time.monotonic() >= deadline:
                    raise LocalError(
                        "La sesion no termino dentro de la espera. Revisa sus logs."
                    )
                time.sleep(0.25)
        return result

    def reset_database_path(self, args):
        values = {}
        env_file = self.root / ".env.native"
        if env_file.exists():
            python = (
                Path(args.python)
                if args.python
                else self.root
                / ".venv"
                / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            )
            if not python.is_file():
                raise LocalError(
                    "No se pudo leer .env.native. Usa --python con el Python de tu instalacion."
                )
            _, raw = self.core.run(
                [
                    str(python),
                    "-c",
                    (
                        "import json,sys; from dotenv import dotenv_values; "
                        "print(json.dumps(dotenv_values(sys.argv[1], interpolate=False)))"
                    ),
                    str(env_file),
                ]
            )
            values = {
                key.upper(): value
                for key, value in json.loads(raw).items()
                if value not in (None, "")
            }
        if (
            values.get("APP_ENV", "development") != "development"
            or values.get("AUTH_MODE", "development") != "development"
            or values.get("MIGRATION_DATABASE_URL")
        ):
            raise LocalError(
                "La limpieza solo admite la base SQLite de desarrollo local."
            )
        database = values.get("DATABASE_URL", "")
        if not database:
            return self.root / ".data/masterlogistica.db"
        prefix = "sqlite+pysqlite:///"
        if not database.startswith(prefix):
            raise LocalError(
                "La limpieza solo admite la base SQLite de desarrollo local."
            )
        path = Path(database[len(prefix) :])
        if not path.is_absolute() or "?" in str(path) or "#" in str(path):
            raise LocalError(
                "DATABASE_URL debe indicar un archivo SQLite con ruta absoluta."
            )
        return path

    def reset(self, args):
        path = self.reset_database_path(args)
        self.stop_session()
        with checkout_lock(self.core.data / "native-start.lock"):
            if port_busy(8000):
                raise LocalError(
                    "El puerto 8000 sigue ocupado. Cierra la API en su terminal antes de borrar los datos."
                )
            if path.is_symlink():
                raise LocalError(
                    "La base configurada es un enlace; indica el archivo SQLite directamente."
                )
            if path.exists():
                try:
                    connection = sqlite3.connect(
                        path.as_uri() + "?mode=rw", uri=True, timeout=1
                    )
                    try:
                        connection.execute("BEGIN EXCLUSIVE")
                        tables = {
                            row[0]
                            for row in connection.execute(
                                "SELECT name FROM sqlite_master WHERE type='table'"
                            )
                        }
                        required = {
                            "local_schema_version",
                            "users",
                            "shipments",
                            "invoices",
                            "provisions",
                        }
                        if not required.issubset(tables):
                            raise LocalError(
                                "El archivo no es una base de MasterLogistica; se conservo."
                            )
                        connection.rollback()
                    finally:
                        connection.close()
                except sqlite3.Error:
                    raise LocalError(
                        "No se pudo abrir la base en exclusiva. Cierra la API y vuelve a intentarlo."
                    ) from None
                path.unlink()
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        self.core.say(
            "Datos locales borrados: registros, referencias, provisiones, facturas, "
            "conciliaciones, documentos e historial. Los consecutivos empezaran de nuevo."
        )
        self.core.say("Ejecuta INICIAR_LOCAL.cmd para abrir los cinco masters vacios.")

    def cleanup(self):
        self.stop.set()
        for _, process in reversed(self.children):
            if process.poll() is None:
                try:
                    if os.name == "nt":
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=4)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.terminate()
                    except OSError:
                        continue
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        for output in self.files:
            output.close()
        if read_json(self.state).get("token") == self.token:
            self.state.unlink(missing_ok=True)
        self.core.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "logs", "reset"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true")
    install = parser.add_mutually_exclusive_group()
    install.add_argument("--install", action="store_true")
    install.add_argument("--skip-install", action="store_true")
    parser.add_argument(
        "--python", help="Interprete Python autorizado para el backend."
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--database", help="Archivo SQLite independiente para esta sesion local."
    )
    args = parser.parse_args(argv)
    if args.database is not None and (args.action != "start" or args.demo):
        parser.error("--database solo se usa al iniciar la API local editable")
    native = Native()
    signal.signal(signal.SIGTERM, lambda *_: native.stop.set())
    try:
        if args.action == "start":
            native.start(args)
        elif args.action == "reset":
            native.reset(args)
        elif args.action in {"status", "stop"}:
            result = (
                native.stop_session()
                if args.action == "stop"
                else control_request(native.state, "status")
            )
            native.core.say(
                json.dumps(result)
                if result
                else "No hay una sesion nativa de esta carpeta respondiendo."
            )
        else:
            for name in ("local", "api", "frontend"):
                path = native.core.data / f"{name}.log"
                if path.exists():
                    native.core.say(f"--- {name} ---", record=False)
                    for line in path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()[-70:]:
                        native.core.say(line, record=False)
        return 0
    except KeyboardInterrupt:
        native.core.say("Deteniendo los procesos de esta sesion local...")
        return 0
    except (LocalError, OSError, ValueError) as error:
        native.core.say(f"ERROR: {error}")
        return 1
    finally:
        native.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
