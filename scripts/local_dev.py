"""Start, inspect and stop this checkout locally, with optional Docker Compose."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "masterlogistica"
URL = "http://127.0.0.1:4200/"
READY_URL = "http://127.0.0.1:8000/health/ready"
CONFIG_URL = "http://127.0.0.1:8000/api/v1/auth/config"
PORTS = {"postgres": 5432, "api": 8000, "web": 4200}
SERVICES = ("postgres", "migrate", "api", "web")


class LocalError(Exception):
    pass


def normalize_path(value):
    value = value.replace("\\", "/").rstrip("/")
    return value.casefold() if os.name == "nt" else value


def local_endpoint(endpoint):
    """Do not operate a remote Docker context from the local launcher."""
    if endpoint.startswith(("unix:///", "npipe:////./pipe/")):
        return True
    parsed = urllib.parse.urlsplit(endpoint)
    return parsed.scheme == "tcp" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def parse_rows(output):
    """Compose v2 versions emit either a JSON array or one object per line."""
    output = output.strip()
    if not output:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in output.splitlines() if line.strip()]
    return data if isinstance(data, list) else [data]


def port_busy(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def frontend_dependencies_current(root):
    """Use npm's installed metadata to avoid reinstalling a matching clean install."""
    expected = read_json(root / "frontend/package-lock.json").get("packages")
    actual = read_json(root / "frontend/node_modules/.package-lock.json").get(
        "packages"
    )
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False
    for name, value in expected.items():
        if not name:
            continue
        installed = actual.get(name)
        if installed is None:
            if value.get("optional"):
                continue
            return False
        if any(
            value.get(key) != installed.get(key) for key in ("version", "integrity")
        ):
            return False
    return True


@contextmanager
def checkout_lock(path):
    """Release automatically on exit, including abnormal process termination."""
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LocalError(
                "Otro lanzador esta trabajando en esta carpeta. Espera a que termine."
            ) from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Launcher:
    def __init__(self, root=ROOT):
        self.root = root.resolve()
        self.data = self.root / ".local-dev"
        self.data.mkdir(exist_ok=True)
        self.state_path = self.data / "state.json"
        self.secrets = []
        self.env = os.environ.copy()
        # Use this checkout's .env, not Compose settings or database passwords
        # inherited from another application in the user's terminal.
        keys = {
            "POSTGRES_PASSWORD",
            "APP_DB_PASSWORD",
            "COMPANY_CODES",
            "BUSINESS_UNITS",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
        }
        for key in list(self.env):
            if key in keys or key.startswith(("COMPOSE_", "ENTRA_")):
                self.env.pop(key)
        self.docker = ""
        self.context = ""
        self.log = logging.getLogger(f"masterlogistica.local.{id(self)}")
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            self.data / "local.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.log.addHandler(handler)
        self.load_secrets()

    def close(self):
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)

    def load_secrets(self, path=None):
        path = path or self.root / ".env"
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                if sep and any(
                    s in key.upper()
                    for s in ("PASSWORD", "SECRET", "TOKEN", "DATABASE_URL")
                ):
                    value = value.strip().strip("\"'")
                    if value:
                        self.secrets.append(value)
                        if key.strip().endswith("DATABASE_URL"):
                            password = urllib.parse.urlsplit(value).password
                            if password:
                                self.secrets.extend(
                                    [password, urllib.parse.unquote(password)]
                                )

    def say(self, message, *, console=True, record=True):
        for secret in self.secrets:
            message = message.replace(secret, "[OCULTO]")
        if record:
            self.log.info(message)
        if console:
            print(message, flush=True)

    def run(self, args, *, stream=False, check=True, timeout=30):
        if stream:
            with subprocess.Popen(
                args,
                cwd=self.root,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            ) as process:
                for line in process.stdout:
                    self.say(line.rstrip())
                code = process.wait()
            output = ""
        else:
            try:
                result = subprocess.run(
                    args,
                    cwd=self.root,
                    env=self.env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise LocalError(
                    "Un comando no respondio a tiempo. Revisa .local-dev/local.log."
                ) from None
            code, output = result.returncode, result.stdout
            if code:
                self.say(result.stderr.strip(), console=False)
        if check and code:
            raise LocalError(
                "El paso anterior no termino correctamente. Revisa .local-dev/local.log "
                "para el diagnostico. Los datos se conservaron."
            )
        return code, output

    def discover_docker(self):
        self.docker = shutil.which("docker") or ""
        if not self.docker and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
                "Docker/Docker/resources/bin/docker.exe"
            )
            if candidate.exists():
                self.docker = str(candidate)
        if not self.docker:
            raise LocalError(
                "No se encontro Docker. El modo Docker necesita Engine en Linux o "
                "Desktop autorizado, con contenedores Linux y Compose v2."
            )
        _, context = self.run([self.docker, "context", "show"])
        self.context = context.strip()
        if not self.context:
            raise LocalError("Docker no tiene un contexto local seleccionado.")
        _, output = self.run(
            [
                self.docker,
                "context",
                "inspect",
                self.context,
                "--format",
                "{{json .Endpoints.docker.Host}}",
            ]
        )
        if not local_endpoint(json.loads(output)):
            raise LocalError(
                "El contexto Docker apunta a un servidor remoto. Selecciona tu Docker "
                "local antes de usar este lanzador. No se modifico ese servidor."
            )

    @property
    def base(self):
        return [self.docker, "--context", self.context]

    def engine(self, *, autostart=False):
        code, kind = self.run(
            self.base + ["info", "--format", "{{.OSType}}"], check=False
        )
        if code and autostart and os.name == "nt":
            desktop = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
                "Docker/Docker/Docker Desktop.exe"
            )
            if desktop.exists():
                self.say("Abriendo Docker Desktop; esperando al motor local...")
                subprocess.Popen(
                    [str(desktop)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                deadline = time.monotonic() + 90
                while code and time.monotonic() < deadline:
                    time.sleep(2)
                    code, kind = self.run(
                        self.base + ["info", "--format", "{{.OSType}}"],
                        check=False,
                        timeout=10,
                    )
        if code:
            raise LocalError(
                "El motor Docker local no responde. Revisa su estado y los permisos con TI."
            )
        if kind.strip() != "linux":
            raise LocalError(
                "Este proyecto requiere un motor Docker de contenedores Linux."
            )
        self.run(self.base + ["compose", "version", "--short"])

    def compose(self, *args, **kwargs):
        return self.run(
            self.base
            + [
                "compose",
                "--project-name",
                PROJECT,
                "--project-directory",
                str(self.root),
                "--env-file",
                str(self.root / ".env"),
                "-f",
                str(self.root / "compose.yaml"),
            ]
            + list(args),
            **kwargs,
        )

    def configure(self):
        if not (self.root / ".env").exists():
            self.say("Preparando la configuracion local por primera vez...")
            self.run(
                [sys.executable, str(self.root / "scripts/configure_local.py")],
                stream=True,
            )
            self.load_secrets()
        else:
            self.say("Se conserva el archivo .env existente y sus contrasenas.")
        self.compose("config", "--quiet")

    def containers(self):
        _, output = self.compose("ps", "--all", "--format", "json")
        rows = parse_rows(output)
        for row in rows:
            _, raw = self.run(
                self.base
                + [
                    "inspect",
                    "--format",
                    "{{json .Config.Labels}}",
                    row["ID"],
                ]
            )
            labels = json.loads(raw) or {}
            if (
                labels.get("com.docker.compose.project") != PROJECT
                or normalize_path(
                    labels.get("com.docker.compose.project.working_dir", "")
                )
                != normalize_path(str(self.root))
                or normalize_path(
                    labels.get("com.docker.compose.project.config_files", "")
                )
                != normalize_path(str(self.root / "compose.yaml"))
            ):
                raise LocalError(
                    "Ya existe un proyecto Docker masterlogistica de otra carpeta o "
                    "configuracion. Se conservo; usa su lanzador o revisa Docker Desktop."
                )
        return rows

    def check_ports(self, rows):
        for service, port in PORTS.items():
            owned = any(
                row.get("Service") == service
                and row.get("State") == "running"
                and any(
                    item.get("PublishedPort") == port and item.get("URL") == "127.0.0.1"
                    for item in row.get("Publishers") or []
                )
                for row in rows
            )
            if port_busy(port) and not owned:
                raise LocalError(
                    f"El puerto {port} esta ocupado por otro proceso. "
                    "Si tienes npm start, DataStage u otra API abierta, detenla en su "
                    "terminal con Ctrl+C. Este lanzador no termina procesos ajenos."
                )

    def fingerprint(self):
        files = [self.root / "compose.yaml", self.root / ".env"]
        for folder, paths in (
            (
                "backend",
                ["Dockerfile", "requirements.lock", "alembic.ini", "app", "migrations"],
            ),
            (
                "frontend",
                [
                    "Dockerfile",
                    "nginx.conf",
                    "package.json",
                    "package-lock.json",
                    "angular.json",
                    "tsconfig.json",
                    "tsconfig.app.json",
                    "src",
                    "public",
                ],
            ),
        ):
            for name in paths:
                path = self.root / folder / name
                files.extend(path.rglob("*") if path.is_dir() else [path])
        digest = hashlib.sha256()
        for path in sorted(set(files)):
            if path.is_file() and not any(
                p.startswith(".") or p == "__pycache__"
                for p in path.relative_to(self.root).parts
            ):
                digest.update(str(path.relative_to(self.root)).encode())
                digest.update(b"\0")
                digest.update(path.read_bytes())
        # .env is deliberately excluded by the hidden-file rule above. Include
        # only its digest so settings changes invalidate a previous ready state.
        digest.update(hashlib.sha256((self.root / ".env").read_bytes()).digest())
        return digest.hexdigest()

    def ready(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(READY_URL, timeout=2) as response:
                if json.load(response).get("status") != "ready":
                    return False
            with opener.open(CONFIG_URL, timeout=2) as response:
                if not isinstance(json.load(response).get("enabled"), bool):
                    return False
            with opener.open(URL, timeout=2) as response:
                return response.status == 200
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def wait_ready(self, timeout):
        self.say("Esperando a la API y a la interfaz...")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ready():
                return
            time.sleep(2)
        raise LocalError(
            "Los servicios no quedaron listos. Ejecuta VER_ESTADO.cmd --mode docker "
            "y VER_LOGS.cmd --mode docker. "
            "Se conservaron la base de datos y los contenedores para diagnostico."
        )

    def start(self, args):
        self.say("[1/5] Comprobando Docker local...")
        self.discover_docker()
        self.engine(autostart=True)
        self.say("[2/5] Comprobando configuracion y puertos...")
        self.configure()
        rows = self.containers()
        self.check_ports(rows)
        fingerprint = self.fingerprint()
        saved = read_json(self.state_path)
        current = saved.get("fingerprint") == fingerprint
        if current and not args.rebuild and self.ready():
            self.say("MasterLogistica ya esta iniciado y listo.")
            self.finish(args)
            return
        need_build = args.rebuild or not current
        if not need_build:
            for service in ("api", "migrate", "web"):
                _, image = self.compose("images", "--quiet", service)
                if not image.strip():
                    need_build = True
                    break
        if need_build:
            self.say(
                "[3/5] Preparando imagenes; la primera vez puede tardar varios minutos..."
            )
            self.compose("build", "api", "migrate", "web", stream=True)
        else:
            self.say("[3/5] Reutilizando las imagenes de la ultima ejecucion.")
        self.say("[4/5] Iniciando PostgreSQL y aplicando migraciones...")
        self.compose(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            str(args.timeout),
            "postgres",
            stream=True,
        )
        if any(
            r.get("Service") in {"api", "web"} and r.get("State") == "running"
            for r in rows
        ):
            self.compose("stop", "web", "api", stream=True)
        self.compose("run", "--rm", "--no-deps", "migrate", stream=True)
        self.say("[5/5] Iniciando API e interfaz...")
        self.compose("up", "-d", "--no-deps", "api", "web", stream=True)
        self.wait_ready(args.timeout)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"fingerprint": fingerprint}), encoding="utf-8")
        temporary.replace(self.state_path)
        self.finish(args)

    def finish(self, args):
        self.say(f"MasterLogistica listo: {URL}")
        self.say(
            "Puedes usar Ver demostracion. El acceso real requiere Microsoft Entra configurado."
        )
        self.say(
            "Para detener: DETENER_LOCAL.cmd --mode docker. "
            "Para diagnostico: VER_ESTADO.cmd --mode docker y VER_LOGS.cmd --mode docker."
        )
        if not args.no_browser:
            try:
                webbrowser.open(URL)
            except webbrowser.Error:
                self.say("Abre la direccion anterior en tu navegador.")

    def inspect_or_stop(self, action):
        if action == "logs":
            for handler in self.log.handlers:
                handler.flush()
            self.say("Ultimas lineas del lanzador:", record=False)
            for line in (
                (self.data / "local.log").read_text(encoding="utf-8").splitlines()[-80:]
            ):
                self.say(line, record=False)
        self.discover_docker()
        self.engine()
        if not (self.root / ".env").exists():
            self.say(
                "No existe configuracion Docker local. Ejecuta INICIAR_LOCAL.cmd --mode docker primero."
            )
            return
        rows = self.containers()
        if action == "stop":
            if not rows:
                self.say("No hay contenedores locales de esta carpeta para detener.")
                return
            self.compose("stop", "web", "api", "migrate", "postgres", stream=True)
            self.say(
                "Servicios locales detenidos. Se conservaron la base, .env y las imagenes."
            )
        elif action == "status":
            for row in rows:
                self.say(
                    f"{row.get('Service')}: {row.get('State')} {row.get('Health') or ''}"
                )
            self.say(f"Acceso: {URL}" if rows else "No hay servicios locales creados.")
            self.say(
                "API e interfaz listas."
                if self.ready()
                else "La aplicacion aun no esta lista."
            )
        else:
            self.say("Logs recientes de los servicios locales:")
            self.compose("logs", "--no-color", "--tail", "80", *SERVICES, stream=True)
            self.say(
                "La salida de construccion y migracion esta en .local-dev/local.log."
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "logs"))
    parser.add_argument("--mode", choices=("native", "docker"), default="native")
    parser.add_argument("--demo", action="store_true")
    install = parser.add_mutually_exclusive_group()
    install.add_argument("--install", action="store_true")
    install.add_argument("--skip-install", action="store_true")
    parser.add_argument(
        "--python", help="Interprete Python autorizado para el backend nativo."
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="Reconstruir las imagenes locales."
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="No abrir el navegador."
    )
    parser.add_argument(
        "--timeout", type=int, default=120, help="Espera de servicios en segundos."
    )
    args = parser.parse_args(argv)
    if not 10 <= args.timeout <= 600:
        parser.error("--timeout debe estar entre 10 y 600 segundos")
    if args.mode == "native":
        if args.rebuild:
            parser.error(
                "--rebuild corresponde al modo Docker; en modo nativo usa --install si hace falta."
            )
        command = [
            sys.executable,
            str(ROOT / "scripts/native_dev.py"),
            args.action,
            "--timeout",
            str(args.timeout),
        ]
        for name in ("no_browser", "demo", "install", "skip_install"):
            if getattr(args, name):
                command.append("--" + name.replace("_", "-"))
        if args.python:
            command.extend(["--python", args.python])
        try:
            return subprocess.call(command)
        except KeyboardInterrupt:
            return 130
    launcher = Launcher()
    try:
        with checkout_lock(launcher.data / "launcher.lock"):
            launcher.say(f"Accion local: {args.action}", console=False)
            if args.action == "start":
                launcher.start(args)
            else:
                launcher.inspect_or_stop(args.action)
        return 0
    except KeyboardInterrupt:
        launcher.say(
            "Se interrumpio la espera. Usa DETENER_LOCAL.cmd para detener los servicios."
        )
        return 130
    except (LocalError, OSError, ValueError) as error:
        launcher.say(f"ERROR: {error}")
        return 1
    finally:
        launcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
