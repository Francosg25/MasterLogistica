"""Exercise native demo and authenticated lifecycle without Docker or a database."""

import argparse
import importlib
import json
import secrets
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
native = importlib.import_module("native_dev")


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="native local ")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.app = native.Native(self.root)
        self.addCleanup(self.app.cleanup)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def server(self, handler):
        self.app.server(0, handler)
        return self.app.servers[-1][0]

    def test_demo_only_serves_configuration_and_health(self):
        server = self.server(native.DemoHandler)
        origin = f"http://127.0.0.1:{server.server_port}"
        with self.opener.open(origin + "/api/v1/auth/config") as response:
            self.assertFalse(json.load(response)["enabled"])
        for endpoint in ("/api/v1/finance/invoices", "/api/v1/shipments"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.opener.open(origin + endpoint)
            self.assertEqual(error.exception.code, 404)
            request = urllib.request.Request(
                origin + endpoint, method="POST", data=b"{}"
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.opener.open(request)
            self.assertEqual(error.exception.code, 403)

    def test_control_rejects_stale_token_before_stop(self):
        server = self.server(self.app.control_handler())
        self.app.state.write_text(json.dumps({"token": secrets.token_urlsafe(32)}))
        with patch.object(native, "CONTROL_PORT", server.server_port):
            self.assertIsNone(native.control_request(self.app.state, "stop"))
        self.assertFalse(self.app.stop.is_set())

    def test_authenticated_control_stops_only_its_session(self):
        server = self.server(self.app.control_handler())
        self.app.state.write_text(json.dumps({"token": self.app.token}))
        with patch.object(native, "CONTROL_PORT", server.server_port):
            status = native.control_request(self.app.state, "status")
            self.assertEqual(status, {"mode": "demo", "ready": False})
            self.assertTrue(native.control_request(self.app.state, "stop")["stopping"])
        self.assertTrue(self.app.stop.is_set())

    def test_cleanup_preserves_other_session_record(self):
        other = secrets.token_urlsafe(32)
        self.app.state.write_text(json.dumps({"token": other}))
        self.app.cleanup()
        self.assertEqual(json.loads(self.app.state.read_text())["token"], other)

    def test_missing_state_does_not_contact_a_server(self):
        with patch.object(native.urllib.request, "build_opener") as opener:
            self.assertIsNone(native.control_request(self.app.state, "stop"))
            opener.assert_not_called()

    def test_existing_frontend_does_not_reinstall_or_invoke_docker(self):
        cli = self.root / "frontend/node_modules/@angular/cli/bin/ng.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// installed")
        metadata = json.dumps(
            {"packages": {"node_modules/@angular/cli": {"version": "21.2.27"}}}
        )
        (self.root / "frontend/package-lock.json").write_text(metadata)
        (self.root / "frontend/node_modules/.package-lock.json").write_text(metadata)
        args = argparse.Namespace(install=False, skip_install=False)
        with (
            patch.object(native.shutil, "which", return_value=sys.executable),
            patch.object(self.app.core, "run", return_value=(0, "24.13.1")) as run,
        ):
            command = self.app.frontend(args)
        self.assertEqual(run.call_count, 2)
        run.assert_any_call([sys.executable, "-p", "process.versions.node"])
        run.assert_any_call(
            [sys.executable, str(self.root / "frontend/scripts/check-toolchain.cjs")],
            stream=True,
        )
        self.assertIn(str(cli), command)
        self.assertIn("127.0.0.1", command)

    def test_backend_never_passes_migration_identity_to_the_api(self):
        (self.root / "backend").mkdir()
        (self.root / "backend/requirements.lock").write_text("synthetic")
        values = {
            "DATABASE_URL": "postgresql+psycopg://masterlogistica_app:app-pass@localhost/test",
            "MIGRATION_DATABASE_URL": "postgresql+psycopg://migration:admin-pass@localhost/test",
            "APP_ENV": "development",
        }
        calls = []

        def run(command, **kwargs):
            calls.append((command, self.app.core.env.copy()))
            return (
                (0, json.dumps(values))
                if "-c" in command and "dotenv_values" in command[-2]
                else (0, "")
            )

        args = argparse.Namespace(
            python=sys.executable, install=False, skip_install=True
        )
        with patch.object(self.app.core, "run", side_effect=run):
            command = self.app.backend(args)
        migration = next(env for command, env in calls if "alembic" in command)
        self.assertEqual(
            migration["MIGRATION_DATABASE_URL"], values["MIGRATION_DATABASE_URL"]
        )
        self.assertNotIn("MIGRATION_DATABASE_URL", self.app.core.env)
        self.assertIn("Settings(_env_file=None)", command[-1])
        self.assertEqual(self.app.core.env["DATABASE_URL"], values["DATABASE_URL"])

    def test_unsupported_node_fails_before_installing_dependencies(self):
        args = argparse.Namespace(install=False, skip_install=False)
        with (
            patch.object(native.shutil, "which", return_value=sys.executable),
            patch.object(self.app.core, "run", return_value=(0, "18.20.0")) as run,
            self.assertRaisesRegex(native.LocalError, "Angular 21 requiere"),
        ):
            self.app.frontend(args)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
