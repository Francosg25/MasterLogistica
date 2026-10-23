"""Launcher invariants without installing Docker or altering real services."""

import argparse
import contextlib
import importlib
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
dev = importlib.import_module("local_dev")


class FakeDocker:
    """Independent stateful responses for the Docker CLI boundary."""

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.rows = []
        self.available = False
        self.fail_migration = False
        self.endpoint = "unix:///var/run/docker.sock"
        self.directory = str(root)

    def run(self, args, **kwargs):
        self.calls.append(args)
        if "context" in args:
            return 0, json.dumps(self.endpoint) if "inspect" in args else "default\n"
        if "info" in args:
            return 0, "linux\n"
        if "inspect" in args:
            return 0, json.dumps(
                {
                    "com.docker.compose.project": dev.PROJECT,
                    "com.docker.compose.project.working_dir": self.directory,
                    "com.docker.compose.project.config_files": str(
                        Path(self.directory) / "compose.yaml"
                    ),
                }
            )
        if "compose" not in args:
            raise AssertionError(args)
        if "ps" in args:
            return 0, json.dumps(self.rows)
        if "images" in args:
            return 0, "sha256:synthetic-image\n"
        if "run" in args and "migrate" in args and self.fail_migration:
            raise dev.LocalError("synthetic migration failure")
        if "up" in args and "api" in args and "web" in args:
            self.available = True
            self.rows = [
                {
                    "ID": s,
                    "Service": s,
                    "State": "running",
                    "Health": "healthy",
                    "Publishers": [{"PublishedPort": port, "URL": "127.0.0.1"}],
                }
                for s, port in dev.PORTS.items()
            ]
        if "stop" in args:
            self.available = False
        return 0, ""


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="master local ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".env").write_text(
            "POSTGRES_PASSWORD=private-admin-value\nAPP_DB_PASSWORD=private-app-value\n",
            encoding="utf-8",
        )
        (self.root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        for folder in ("backend/app", "frontend/src", "frontend/public"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "frontend/package-lock.json").write_text("{}", encoding="utf-8")
        self.launcher = dev.Launcher(self.root)
        self.addCleanup(self.launcher.close)
        self.fake = FakeDocker(self.root)
        for target, value in (
            ("run", self.fake.run),
            ("ready", lambda: self.fake.available),
        ):
            patcher = patch.object(self.launcher, target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (("shutil.which", "docker"), ("port_busy", False)):
            patcher = patch("local_dev." + target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.args = argparse.Namespace(rebuild=False, no_browser=True, timeout=10)

    def compose_calls(self):
        return [c for c in self.fake.calls if "compose" in c and "version" not in c]

    def test_start_migrates_before_api_and_reuses_ready_services(self):
        before = (self.root / ".env").read_bytes()
        self.launcher.start(self.args)
        calls = self.compose_calls()
        migration = next(
            i for i, c in enumerate(calls) if "run" in c and "migrate" in c
        )
        api = next(i for i, c in enumerate(calls) if "up" in c and "api" in c)
        self.assertLess(migration, api)
        self.assertEqual((self.root / ".env").read_bytes(), before)
        for call in calls:
            self.assertIn(str(self.root / "compose.yaml"), call)
            self.assertIn(str(self.root / ".env"), call)
            self.assertIn("--context", call)
            self.assertNotIn("down", call)
        self.fake.calls.clear()
        self.launcher.start(self.args)
        self.assertFalse(
            any("build" in c or "run" in c or "up" in c for c in self.compose_calls())
        )

    def test_stopped_services_reuse_images_and_still_migrate(self):
        self.launcher.start(self.args)
        self.fake.calls.clear()
        self.fake.available = False
        for row in self.fake.rows:
            row["State"] = "exited"
        self.launcher.start(self.args)
        self.assertFalse(any("build" in c for c in self.compose_calls()))
        self.assertTrue(
            any("run" in c and "migrate" in c for c in self.compose_calls())
        )

    def test_source_change_rebuilds_and_stops_api_before_migration(self):
        self.launcher.start(self.args)
        self.fake.calls.clear()
        (self.root / "frontend/src/main.ts").write_text("new source", encoding="utf-8")
        self.launcher.start(self.args)
        calls = self.compose_calls()
        self.assertTrue(any("build" in c for c in calls))
        stop = next(i for i, c in enumerate(calls) if "stop" in c)
        migration = next(i for i, c in enumerate(calls) if "run" in c)
        self.assertLess(stop, migration)

    def test_migration_failure_never_publishes_or_records_success(self):
        self.fake.fail_migration = True
        with self.assertRaisesRegex(dev.LocalError, "migration failure"):
            self.launcher.start(self.args)
        self.assertFalse(any("up" in c and "api" in c for c in self.compose_calls()))
        self.assertFalse(self.launcher.state_path.exists())

    def test_busy_foreign_port_causes_no_build_or_stop(self):
        with (
            patch("local_dev.port_busy", return_value=True),
            self.assertRaisesRegex(dev.LocalError, "ocupado"),
        ):
            self.launcher.start(self.args)
        self.assertFalse(
            any("build" in c or "stop" in c or "up" in c for c in self.compose_calls())
        )

    def test_remote_context_is_rejected_before_compose(self):
        self.fake.endpoint = "ssh://corporate-production.example"
        with self.assertRaisesRegex(dev.LocalError, "remoto"):
            self.launcher.start(self.args)
        self.assertEqual(self.compose_calls(), [])

    def test_stop_refuses_project_from_another_directory(self):
        self.fake.rows = [{"ID": "other", "Service": "api", "State": "running"}]
        self.fake.directory = str(self.root / "another checkout")
        with self.assertRaisesRegex(dev.LocalError, "otra carpeta"):
            self.launcher.inspect_or_stop("stop")
        self.assertFalse(any("stop" in c for c in self.compose_calls()))

    def test_stop_preserves_env_state_and_volumes(self):
        self.launcher.start(self.args)
        before = (self.root / ".env").read_bytes()
        self.fake.calls.clear()
        self.launcher.inspect_or_stop("stop")
        self.assertEqual((self.root / ".env").read_bytes(), before)
        self.assertTrue(self.launcher.state_path.exists())
        self.assertTrue(any("stop" in c for c in self.compose_calls()))
        self.assertFalse(
            any(
                "down" in c or "--volumes" in c or "-v" in c
                for c in self.compose_calls()
            )
        )

    def test_environment_uses_local_file_instead_of_caller_passwords(self):
        with patch.dict(
            "os.environ",
            {
                "POSTGRES_PASSWORD": "foreign-password",
                "COMPOSE_FILE": "production.yaml",
                "DOCKER_HOST": "ssh://remote.example",
                "ENTRA_TENANT_ID": "foreign-tenant",
            },
        ):
            other = dev.Launcher(self.root)
        try:
            for key in (
                "POSTGRES_PASSWORD",
                "COMPOSE_FILE",
                "DOCKER_HOST",
                "ENTRA_TENANT_ID",
            ):
                self.assertNotIn(key, other.env)
        finally:
            other.close()

    def test_real_child_output_is_redacted_in_console_and_log(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            # Exercise the real subprocess adapter, not the fake Docker boundary.
            dev.Launcher.run(
                self.launcher,
                [
                    sys.executable,
                    "-c",
                    "print('failure with private-admin-value')",
                ],
                stream=True,
            )
        self.assertNotIn("private-admin-value", buffer.getvalue())
        self.assertIn("[OCULTO]", buffer.getvalue())
        self.assertNotIn(
            "private-admin-value", (self.launcher.data / "local.log").read_text()
        )

    def test_fingerprint_tracks_env_and_lockfile_ignoring_generated_files(self):
        first = self.launcher.fingerprint()
        (self.root / "frontend/package-lock.json").write_text(
            '{"changed":true}', encoding="utf-8"
        )
        second = self.launcher.fingerprint()
        self.assertNotEqual(first, second)
        (self.root / "frontend/src/__pycache__").mkdir()
        (self.root / "frontend/src/__pycache__/cache.pyc").write_bytes(b"generated")
        self.assertEqual(second, self.launcher.fingerprint())
        (self.root / ".env").write_text("APP_DB_PASSWORD=new-value", encoding="utf-8")
        self.assertNotEqual(second, self.launcher.fingerprint())


class ProtocolTests(unittest.TestCase):
    def test_local_contexts_only(self):
        for endpoint in (
            "unix:///var/run/docker.sock",
            "npipe:////./pipe/docker_engine",
            "tcp://127.0.0.1:2375",
        ):
            self.assertTrue(dev.local_endpoint(endpoint))
        for endpoint in (
            "ssh://host.example",
            "tcp://host.example:2376",
            "npipe:////server/pipe/docker",
        ):
            self.assertFalse(dev.local_endpoint(endpoint))

    def test_compose_json_array_and_json_lines(self):
        rows = [{"Service": "api"}, {"Service": "web"}]
        self.assertEqual(dev.parse_rows(json.dumps(rows)), rows)
        self.assertEqual(
            dev.parse_rows("\n".join(json.dumps(row) for row in rows)), rows
        )
        self.assertEqual(dev.parse_rows(""), [])

    def test_exclusive_lock_and_release(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "launcher.lock"
            with (
                dev.checkout_lock(path),
                self.assertRaises(dev.LocalError),
                dev.checkout_lock(path),
            ):
                self.fail("Second launcher acquired the lock")
            with dev.checkout_lock(path):
                pass

    def test_port_probe_leaves_listener_running(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.assertTrue(dev.port_busy(listener.getsockname()[1]))
            self.assertGreater(listener.fileno(), -1)

    def test_readiness_requires_backend_config_and_frontend(self):
        responses = {
            "/ready": {"status": "ready"},
            "/config": {"enabled": False},
            "/": "web",
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                value = responses.get(self.path)
                self.send_response(200 if value is not None else 503)
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f"http://127.0.0.1:{server.server_port}"
            with tempfile.TemporaryDirectory() as folder:
                launcher = dev.Launcher(Path(folder))
                try:
                    with patch.multiple(
                        dev,
                        URL=origin + "/",
                        READY_URL=origin + "/ready",
                        CONFIG_URL=origin + "/config",
                    ):
                        self.assertTrue(launcher.ready())
                        responses["/config"] = None
                        self.assertFalse(launcher.ready())
                        responses["/config"] = {"enabled": False}
                        responses["/ready"] = {"status": "not ready"}
                        self.assertFalse(launcher.ready())
                finally:
                    launcher.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
