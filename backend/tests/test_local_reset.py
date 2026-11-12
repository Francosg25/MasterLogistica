"""A local reset removes real financial data and recreates five empty masters."""

import argparse
import importlib
import sys
from pathlib import Path

from sqlalchemy import text

from app.local_schema import LOCAL_SUPPLIER
from app.main import create_app
from tests.test_catalog_cleanup import create
from tests.test_finance import invoice, provision
from tests.test_local import local_client, local_settings


def test_reset_and_restart_clear_all_operational_tables_and_sequences(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    native = importlib.import_module("native_dev")
    monkeypatch.setattr(native, "port_busy", lambda port: False)
    path = tmp_path / ".data/masterlogistica.db"
    (tmp_path / ".env.native").write_text(f"DATABASE_URL=sqlite+pysqlite:///{path}\n")
    settings = local_settings(path)
    app = create_app(settings)
    with local_client(app) as client:
        environment = {"client": client, "headers": lambda role: {}, "supplier_id": LOCAL_SUPPLIER}
        shipment = create(client)
        provision(environment, shipment)
        row = invoice(environment, shipment, company_code="MXG")
        assert row["applied_amount"] == "500.0000"
        assert client.get("/api/v1/finance/history").json()["items"]
    reset = native.Native(tmp_path)
    try:
        reset.reset(argparse.Namespace(python=sys.executable))
    finally:
        reset.cleanup()
    assert not path.exists()
    fresh = create_app(settings)
    with local_client(fresh) as client:
        owners = client.get("/api/v1/masters/owners").json()
        assert {owner["display_name"] for owner in owners} == {"DENI", "MAG", "NAT", "ANDREA", "ALEXA"}
        assert client.get("/api/v1/shipments").json()["total"] == 0
        assert client.get("/api/v1/finance/invoices").json()["items"] == []
        assert client.get("/api/v1/finance/history").json()["items"] == []
        with fresh.state.engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).scalars().all()
            for table in tables:
                if table not in {"local_schema_version", "users", "suppliers", "reference_counters"}:
                    assert connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() == 0
            assert connection.execute(text(
                "SELECT COUNT(*) FROM reference_counters WHERE last_value != 0"
            )).scalar() == 0
        assert create(client)["reference_sequence"] == 1
