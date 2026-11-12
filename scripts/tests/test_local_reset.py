"""Reset only the configured local database, after its owning session stops."""

import argparse
import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
native = importlib.import_module("native_dev")


class LocalResetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="reset master ")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.app = native.Native(self.root)
        self.addCleanup(self.app.cleanup)
        self.args = argparse.Namespace(python=sys.executable)
        patcher = patch.object(native, "port_busy", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def database(self, path=None):
        path = path or self.root / ".data/masterlogistica.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            for name in (
                "local_schema_version",
                "users",
                "shipments",
                "invoices",
                "provisions",
                "reconciliation_allocations",
                "reconciliation_logs",
                "reference_counters",
                "documents",
                "suppliers",
            ):
                connection.execute(f"CREATE TABLE {name} (value TEXT)")
                connection.execute(f"INSERT INTO {name} VALUES ('synthetic')")
        return path

    def test_reset_removes_all_data_and_sidecars_but_keeps_project_files(self):
        path = self.database()
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(path) + suffix).touch()
        files = [self.root / "README.md", self.root / "original.xlsx"]
        for file in files:
            file.write_bytes(b"keep")
        self.app.reset(self.args)
        self.assertFalse(path.exists())
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(path) + suffix).exists())
        for file in files:
            self.assertEqual(file.read_bytes(), b"keep")
        self.app.reset(self.args)  # Safe to run again before starting the app.

    def test_custom_database_is_used_instead_of_default_and_config_is_preserved(self):
        default = self.database()
        custom = self.database(self.root / "custom data/test.db")
        env_file = self.root / ".env.native"
        text = f"DATABASE_URL=sqlite+pysqlite:///{custom}\n"
        env_file.write_text(text)
        values = {"DATABASE_URL": f"sqlite+pysqlite:///{custom}"}
        with patch.object(self.app.core, "run", return_value=(0, json.dumps(values))):
            self.app.reset(self.args)
        self.assertFalse(custom.exists())
        self.assertTrue(default.exists())
        self.assertEqual(env_file.read_text(), text)

    def test_non_local_configuration_is_rejected_before_stopping_or_deleting(self):
        path = self.database()
        (self.root / ".env.native").write_text("# explicit configuration\n")
        for values in (
            {"DATABASE_URL": "postgresql+psycopg://localhost/corporate"},
            {"APP_ENV": "production"},
            {"AUTH_MODE": "entra"},
            {"MIGRATION_DATABASE_URL": "postgresql+psycopg://localhost/corporate"},
            {"DATABASE_URL": "sqlite+pysqlite:///relative.db"},
            {"DATABASE_URL": f"sqlite+pysqlite:///{path}?uri=true"},
        ):
            with (
                self.subTest(values=values),
                patch.object(
                    self.app.core, "run", return_value=(0, json.dumps(values))
                ),
                patch.object(self.app, "stop_session") as stop,
                self.assertRaises(native.LocalError),
            ):
                self.app.reset(self.args)
            stop.assert_not_called()
            self.assertTrue(path.exists())

    def test_inherited_corporate_settings_do_not_change_default_reset_target(self):
        path = self.database()
        self.app.core.env.update(
            {"DATABASE_URL": "postgresql+psycopg://host/corporate"}
        )
        self.app.reset(self.args)
        self.assertFalse(path.exists())

    def test_other_sqlite_database_is_preserved(self):
        path = self.root / ".data/masterlogistica.db"
        path.parent.mkdir()
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE another_app (value TEXT)")
            connection.execute("INSERT INTO another_app VALUES ('keep')")
        with self.assertRaisesRegex(
            native.LocalError, "no es una base de MasterLogistica"
        ):
            self.app.reset(self.args)
        with sqlite3.connect(path) as connection:
            self.assertEqual(
                connection.execute("SELECT value FROM another_app").fetchone(),
                ("keep",),
            )

    def test_owned_session_is_stopped_and_awaited_before_deletion(self):
        path = self.database()
        responses = iter([{"stopping": True}, {"ready": True}, None])

        def control(state, action):
            self.assertEqual(state, self.app.state)
            self.assertTrue(path.exists())
            return next(responses)

        with (
            patch.object(native, "control_request", side_effect=control) as request,
            patch.object(native.time, "sleep"),
        ):
            self.app.reset(self.args)
        self.assertEqual(
            [call.args[1] for call in request.call_args_list],
            ["stop", "status", "status"],
        )
        self.assertFalse(path.exists())

    def test_session_timeout_preserves_all_data(self):
        path = self.database()
        with (
            patch.object(native, "control_request", return_value={"ready": True}),
            patch.object(native.time, "monotonic", side_effect=[0, 16]),
            self.assertRaisesRegex(native.LocalError, "no termino"),
        ):
            self.app.reset(self.args)
        self.assertTrue(path.exists())

    def test_manually_started_api_is_not_killed_or_its_data_deleted(self):
        path = self.database()
        with (
            patch.object(native, "port_busy", return_value=True),
            patch.object(native.os, "killpg") as kill,
            self.assertRaisesRegex(native.LocalError, "Cierra la API"),
        ):
            self.app.reset(self.args)
        kill.assert_not_called()
        self.assertTrue(path.exists())

    def test_running_launcher_lock_preserves_database(self):
        path = self.database()
        with (
            native.checkout_lock(self.app.core.data / "native-start.lock"),
            self.assertRaisesRegex(native.LocalError, "Otro lanzador"),
        ):
            self.app.reset(self.args)
        self.assertTrue(path.exists())

    def test_database_in_use_is_preserved(self):
        path = self.database()
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        connection.execute("BEGIN IMMEDIATE")
        with self.assertRaisesRegex(native.LocalError, "en exclusiva"):
            self.app.reset(self.args)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
