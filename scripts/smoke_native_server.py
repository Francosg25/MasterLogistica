"""Exercise the real Linux HTTPS proxy and production API in an isolated local test."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from check_deployment import check

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def smoke(nginx, web_root=None):
    with tempfile.TemporaryDirectory(prefix="masterlogistica-https-") as folder:
        test = Path(folder)
        key, cert = test / "key.pem", test / "cert.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        api_port, tls_port, http_port = free_port(), free_port(), free_port()
        if web_root is None:
            web_root = test / "web"
            web_root.mkdir()
            (web_root / "index.html").write_text(
                "<!doctype html><html><body>Native deployment smoke</body></html>"
            )
        values = {
            "APP_ENV": "production",
            "DATABASE_URL": f"postgresql+psycopg://masterlogistica_app:test-only-password@localhost:1/masterlogistica_test?sslmode=verify-full&sslrootcert={cert}",
            "ENTRA_TENANT_ID": "10000000-0000-0000-0000-000000000001",
            "ENTRA_API_CLIENT_ID": "20000000-0000-0000-0000-000000000001",
            "ENTRA_FRONTEND_CLIENT_ID": "30000000-0000-0000-0000-000000000001",
            "ENTRA_ALLOWED_CLIENT_IDS": '["30000000-0000-0000-0000-000000000001"]',
            "BUSINESS_UNITS": '{"T01":"Test unit"}',
            "ALLOWED_HOSTS": '["localhost"]',
            "ALLOWED_ORIGINS": json.dumps([f"https://localhost:{tls_port}"]),
            "ENFORCE_HTTPS": "true",
            "TRUSTED_PROXY_IPS": '["127.0.0.1"]',
        }
        env_file = test / "api.env"
        env_file.write_text(
            "\n".join(f"{name}={value}" for name, value in values.items())
        )
        env_file.chmod(0o600)
        server = (
            (ROOT / "deploy/linux/nginx.conf.in")
            .read_text()
            .replace("@DOMAIN@", "localhost")
        )
        for old, new in (
            ("listen 80;", f"listen 127.0.0.1:{http_port};"),
            ("listen 443 ssl;", f"listen 127.0.0.1:{tls_port} ssl;"),
            (
                "https://localhost$request_uri",
                f"https://localhost:{tls_port}$request_uri",
            ),
            ("/etc/masterlogistica/tls/fullchain.pem", str(cert)),
            ("/etc/masterlogistica/tls/privkey.pem", str(key)),
            ("/opt/masterlogistica/current/web", str(web_root.resolve())),
            ("127.0.0.1:8000", f"127.0.0.1:{api_port}"),
        ):
            server = server.replace(old, new)
        config = test / "nginx.conf"
        test_user = "user root root;\n" if os.geteuid() == 0 else ""
        config.write_text(
            test_user
            + f"master_process off;\npid {test}/nginx.pid;\nerror_log {test}/error.log;\n"
            "events { worker_connections 128; }\nhttp {\naccess_log off;\n"
            "types { text/html html; application/javascript js; text/css css; }\n"
            f"client_body_temp_path {test}/body;\nproxy_temp_path {test}/proxy;\n"
            f"fastcgi_temp_path {test}/fastcgi;\nuwsgi_temp_path {test}/uwsgi;\nscgi_temp_path {test}/scgi;\n"
            + server
            + "\n}\n"
        )
        nginx_args = [nginx, "-p", str(test) + "/", "-c", str(config)]
        syntax = subprocess.run(
            nginx_args + ["-t"], capture_output=True, text=True, check=False
        )
        if syntax.returncode:
            raise RuntimeError(syntax.stderr)
        children = []
        try:
            with (test / "api.log").open("w") as output:
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "app.runtime",
                            "serve",
                            "--env-file",
                            str(env_file),
                            "--port",
                            str(api_port),
                        ],
                        cwd=ROOT / "backend",
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
                )
                children.append(
                    subprocess.Popen(
                        nginx_args + ["-g", "daemon off;"],
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
                )
                context = ssl.create_default_context(cafile=cert)
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=context),
                )
                origin = f"https://localhost:{tls_port}"
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError((test / "api.log").read_text())
                    try:
                        with opener.open(
                            origin + "/api/v1/auth/config", timeout=2
                        ) as response:
                            if json.load(response).get("enabled"):
                                break
                    except OSError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("HTTPS smoke startup timed out")
                check(origin, cert)
                request = urllib.request.Request(
                    origin + "/api/v1/auth/config",
                    headers={"X-Forwarded-Proto": "http"},
                )
                with opener.open(request, timeout=3) as response:
                    assert response.status == 200, (
                        "Proxy did not replace an incoming scheme header"
                    )
                with opener.open(origin + "/masters/example", timeout=3) as response:
                    assert b"<html" in response.read(8192).lower(), (
                        "SPA fallback failed"
                    )
                for endpoint, expected in (
                    ("/api/v1/auth/me", 401),
                    ("/health/ready", 503),
                ):
                    try:
                        opener.open(origin + endpoint, timeout=8)
                    except urllib.error.HTTPError as error:
                        assert error.code == expected, (endpoint, error.code)
                    else:
                        raise AssertionError("Expected auth/DB failure was hidden")
                print(
                    "HTTPS smoke passed: trusted certificate, proxy scheme, SPA fallback, auth and database-unavailable response."
                )
        finally:
            for child in reversed(children):
                child.terminate()
            for child in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nginx", default=shutil.which("nginx"))
    parser.add_argument("--web-root", type=Path)
    args = parser.parse_args()
    if os.name != "posix" or not args.nginx or not shutil.which("openssl"):
        parser.exit(
            1, "This smoke test needs Linux, nginx, openssl and backend dependencies.\n"
        )
    smoke(args.nginx, args.web_root)


if __name__ == "__main__":
    main()
