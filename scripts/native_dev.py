"""Local Python/Angular launcher; no Docker or virtual machine is required."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
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
    port_busy,
    read_json,
)

CONTROL_PORT = 8317


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
        self.mode = "demo"
        self.is_ready = False

    def frontend(self, args):
        node = shutil.which("node")
        if not node:
            raise LocalError(
                "No se encontro Node. Usa la instalacion autorizada compatible con Angular 21."
            )
        cli = self.root / "frontend/node_modules/@angular/cli/bin/ng.js"
        installed = self.core.data / "native-frontend.json"
        lock = self.root / "frontend/package-lock.json"
        import hashlib

        digest = hashlib.sha256(lock.read_bytes()).hexdigest()
        saved = read_json(installed).get("lock")
        install = (
            args.install or not cli.exists() or (saved is not None and saved != digest)
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
                self.core.run(
                    [
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "--require-hashes",
                        "-r",
                        str(self.root / "backend/requirements.lock"),
                    ],
                    stream=True,
                )
            marker.write_text(
                json.dumps({"lock": digest, "python": str(python)}), encoding="utf-8"
            )
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
            key: value for key, value in json.loads(raw).items() if value is not None
        }
        if values.get("APP_ENV", "development") != "development":
            raise LocalError(
                "El lanzador nativo solo admite APP_ENV=development en .env.native."
            )
        if not values.get("DATABASE_URL", "").startswith("postgresql+psycopg://"):
            raise LocalError(
                "Configura PostgreSQL en DATABASE_URL dentro de .env.native."
            )
        self.core.secrets.extend(
            value
            for key, value in values.items()
            if "PASSWORD" in key or key.endswith("DATABASE_URL")
        )
        # Never inherit a production connection or migration identity from the terminal.
        for key in (
            "DATABASE_URL",
            "MIGRATION_DATABASE_URL",
            "APP_ENV",
            "ENFORCE_HTTPS",
            "ALLOWED_HOSTS",
            "ALLOWED_ORIGINS",
        ):
            self.core.env.pop(key, None)
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
        if values.get("MIGRATION_DATABASE_URL"):
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
                        self, 200, {"mode": owner.mode, "ready": owner.is_ready}
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
        current = control_request(self.state, "status")
        if current:
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
            self.mode = (
                "database"
                if (self.root / ".env.native").exists() and not args.demo
                else "demo"
            )
            self.core.say(f"Inicio directo sin Docker. Modo: {self.mode}.")
            if self.mode == "demo":
                self.core.say(
                    "Datos ficticios de solo lectura. Para guardar datos se necesita PostgreSQL y .env.native."
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
                        "No termino el arranque. Revisa VER_LOGS.cmd y la conexion PostgreSQL si usas datos reales."
                    )
                self.stop.wait(0.5)

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
    parser.add_argument("action", choices=("start", "stop", "status", "logs"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true")
    install = parser.add_mutually_exclusive_group()
    install.add_argument("--install", action="store_true")
    install.add_argument("--skip-install", action="store_true")
    parser.add_argument(
        "--python", help="Interprete Python autorizado para el backend."
    )
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    native = Native()
    try:
        if args.action == "start":
            native.start(args)
        elif args.action in {"status", "stop"}:
            result = control_request(native.state, args.action)
            if args.action == "stop" and result:
                deadline = time.monotonic() + 15
                while (
                    control_request(native.state, "status")
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.25)
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
