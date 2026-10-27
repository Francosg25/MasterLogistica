"""Owner-specific Excel capture, real persistence and additive schema upgrades."""

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event

from app.local_schema import LOCAL_SUPPLIER, SCHEMA_VERSION
from app.main import create_app
from app.master_layouts import LAYOUTS
from app.models import Shipment
from tests.test_local import local_client, local_settings

ROOT = Path(__file__).resolve().parents[2]
BASE = dict(
    company_code="MXG",
    process_code="RM",
    operation_code="LI",
    reference_year=2026,
    business_unit="M01",
    department_code="MAT",
    ship_date="2026-10-26",
)


@pytest.fixture
def local_master(tmp_path):
    settings = local_settings(tmp_path / "masters.db")
    app = create_app(settings)
    with local_client(app) as client:
        yield settings, app, client


def create(client, **values):
    response = client.post("/api/v1/shipments", json={**BASE, **values})
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, row, **values):
    response = client.patch(
        "/api/v1/shipments/" + row["id"],
        json={"expected_version": row["row_version"], **values},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_contracts_follow_each_source_and_demo_matches_backend():
    frontend = json.loads((ROOT / "frontend/public/master-layouts.json").read_text())
    assert frontend["layouts"] == LAYOUTS
    assert {code: len(layout["fields"]) for code, layout in LAYOUTS.items()} == {
        "DENI": 51,
        "ANDREA": 47,
        "MAG": 32,
        "NAT": 34,
        "ALEXA": 41,
    }
    for layout in LAYOUTS.values():
        keys = [f["key"] for f in layout["fields"]]
        assert keys[:3] == ["master.sec", "master.owner", "reference_raw"]
        assert len(set(keys)) == len(keys)
        assert layout["fields"][0]["source_column"] == "B"
        assert "A" not in [f["source_column"] for f in layout["fields"]]
    assert LAYOUTS["DENI"]["fields"][-1]["source_column"] == "BA"
    assert "AP" not in [f["source_column"] for f in LAYOUTS["DENI"]["fields"]]


@pytest.mark.parametrize(
    "code,extras",
    [
        (
            "DENI",
            {
                "container_number": "CONT-SYNTHETIC",
                "weight": "100 kg",
                "file_record": "Listo",
                "guarantee_payment": "No",
            },
        ),
        (
            "ANDREA",
            {
                "arrival_port": "Puerto de prueba",
                "vessel": "Buque de prueba",
                "actual_arrival_port": "2026-10-25",
                "claim_amount": "25.50 USD",
            },
        ),
        (
            "MAG",
            {
                "claim_report": "CLAIM-TEST",
                "claim_user": "Usuario de ejemplo",
                "claim_status": "En revisión",
            },
        ),
        (
            "NAT",
            {"export_invoice": "EXPORT-TEST", "claim_report": "REPORT-TEST", "claim_amount": "0"},
        ),
        (
            "ALEXA",
            {
                "invoice_number": "FACT-TEST",
                "weight": "100",
                "packages": "4",
                "part_number": "NP-TEST",
                "pfa_number": "PFA libre",
            },
        ),
    ],
)
def test_each_master_persists_its_columns_and_partial_changes(local_master, code, extras):
    settings, _, client = local_master
    owner = next(r for r in client.get("/api/v1/masters/owners").json() if r["layout_code"] == code)
    row = create(client, owner_id=owner["id"], master_data={**extras, "owner": "Nombre manual"})
    assert row["owner_id"] == owner["id"]
    assert row["master_data"] == {**extras, "owner": "Nombre manual"}
    row = patch(client, row, master_data={"pedimento": "000-TEST", "owner": "Otro nombre manual"})
    assert row["master_data"] == {**extras, "owner": "Otro nombre manual", "pedimento": "000-TEST"}
    row = patch(client, row, master_data={"owner": None})
    assert row["master_data"]["owner"] is None
    assert all(row["master_data"][key] == value for key, value in extras.items())
    with local_client(create_app(settings)) as restarted:
        assert restarted.get("/api/v1/shipments/" + row["id"]).json() == row
        data = restarted.get(
            "/api/v1/masters/shipments", params={"owner_id": owner["id"], "q": "000-TEST"}
        ).json()
        assert [r["id"] for r in data["items"]] == [row["id"]]


@pytest.mark.parametrize(
    "bad",
    [
        {"part_number": "Solo ALEXA"},
        {"vessel": "x" * 251},
        {"etd_origin_port": "2026-02-30"},
        {"etd_origin_port": "26/10/2026"},
        {"unrecognized": "x"},
    ],
)
def test_profile_validation_is_atomic(local_master, bad):
    _, _, client = local_master
    row = create(client, master_data={"vessel": "Conservar"})
    path = "/api/v1/shipments/" + row["id"]
    response = client.patch(
        path, json={"expected_version": 1, "company_code": "MXT", "master_data": bad}
    )
    assert response.status_code == 422, response.text
    assert client.get(path).json() == row


def test_search_and_history_use_the_actual_master_column_labels(local_master):
    _, _, client = local_master
    mag = next(r for r in client.get("/api/v1/masters/owners").json() if r["layout_code"] == "MAG")
    row = create(
        client,
        owner_id=mag["id"],
        master_data={"claim_user": "Prueba daño", "claim_report": "Inicial"},
    )
    row = patch(client, row, master_data={"claim_report": "Corregido"})
    results = client.get(
        "/api/v1/masters/shipments", params={"q": "daño", "owner_id": mag["id"]}
    ).json()
    assert [r["id"] for r in results["items"]] == [row["id"]]
    history = client.get(
        "/api/v1/finance/history", params={"shipment_id": row["id"], "action": "SHIPMENT_UPDATED"}
    ).json()
    assert history["items"][0]["changes"] == [
        {
            "field": "master.claim_report",
            "label": "# Reporte claim",
            "before": "Inicial",
            "after": "Corregido",
        },
    ]


def test_manual_reference_creation_keeps_aliases_and_automatic_counter(local_master):
    _, _, client = local_master
    first = create(client, reference_raw="RM1-0042LI26-M01-MAT", master_data={"sec": "42"})
    assert first["reference_raw"] == "RM1-0042LI26-M01-MAT"
    aliases = client.get("/api/v1/shipments/" + first["id"] + "/identifiers").json()
    assert [r["normalized_value"] for r in aliases] == [first["reference_normalized"]]
    duplicate = client.post(
        "/api/v1/shipments", json={**BASE, "reference_raw": "rm1-0042li26-m01-mat"}
    )
    assert duplicate.status_code == 422, duplicate.text
    second = create(client)
    assert second["reference_sequence"] == 43
    manual = create(
        client, reference_raw="REF / MANUAL DE EJEMPLO", operation_code="Operación manual"
    )
    assert manual["reference_normalized"] == "REF/MANUALDEEJEMPLO"
    assert manual["operation_code"] == "Operación manual"


def test_existing_typed_values_remain_visible_and_can_be_cleared(local_master):
    _, app, client = local_master
    row = create(client)
    with app.state.session_factory() as session, session.begin():
        stored = session.get(Shipment, UUID(row["id"]))
        stored.arrival_port = "Puerto existente"
        stored.weight_kg = Decimal("25.5")
        stored.scs_security_status = "Liberado"
        stored.customs_appointment = datetime(2026, 10, 26, 14, 30, tzinfo=UTC)
    row = client.get("/api/v1/shipments/" + row["id"]).json()
    assert row["master_data"] == {
        "arrival_port": "Puerto existente",
        "weight": "25.5000",
        "scs_security_status": "Liberado",
        "customs_appointment": "2026-10-26 14:30+00:00",
    }
    row = patch(client, row, master_data={"arrival_port": None})
    assert row["master_data"]["arrival_port"] is None
    assert row["master_data"]["weight"] == "25.5000"


def previous_database(tmp_path):
    path = tmp_path / "previous.db"
    settings = local_settings(path)
    app = create_app(settings)
    with local_client(app) as client:
        row = create(client, comments="Conservar historial y vínculos")
        provision = client.post(
            "/api/v1/finance/provisions",
            json=dict(
                shipment_id=row["id"],
                supplier_id=str(LOCAL_SUPPLIER),
                charge_code="FREIGHT",
                provision_date="2026-10-26",
                amount="100",
                extra_charges="0",
                currency="USD",
            ),
        )
        assert provision.status_code == 201, provision.text
        provision = provision.json()
        invoice = client.post(
            "/api/v1/finance/invoices",
            json=dict(
                company_code="MXG",
                supplier_id=str(LOCAL_SUPPLIER),
                invoice_number="TEST-MIGRATION",
                issue_date="2026-10-26",
                accounting_period="2026-10-01",
                currency="USD",
                lines=[
                    dict(
                        reference=row["reference_raw"],
                        charge_code="FREIGHT",
                        net_amount="100",
                        tax_amount="0",
                    )
                ],
            ),
        )
        assert invoice.status_code == 201, invoice.text
        invoice = client.get("/api/v1/finance/invoices?q=TEST-MIGRATION").json()["items"][0]
        with app.state.engine.begin() as connection:
            before = {
                table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
                for table in [
                    "shipments",
                    "provisions",
                    "invoices",
                    "reconciliation_allocations",
                    "reconciliation_logs",
                ]
            }
            connection.exec_driver_sql("ALTER TABLE shipments DROP COLUMN master_data")
            connection.exec_driver_sql("UPDATE local_schema_version SET version = 3")
    return settings, path, row, provision, invoice, before


def test_version_three_upgrade_preserves_records_financial_links_and_audit(tmp_path):
    settings, _, row, provision, invoice, before = previous_database(tmp_path)
    app = create_app(settings)
    with local_client(app) as client:
        stored = client.get("/api/v1/shipments/" + row["id"]).json()
        assert stored == {**row, "master_data": {}}
        stored_invoice = client.get("/api/v1/finance/invoices?q=TEST-MIGRATION").json()["items"][0]
        assert stored_invoice == invoice
        balances = client.get("/api/v1/finance/balances?month=2026-10-01").json()["items"]
        assert balances[0]["id"] == provision["id"]
        assert Decimal(balances[0]["closing_amount"]) == 0
        with app.state.engine.begin() as connection:
            assert (
                connection.exec_driver_sql("SELECT version FROM local_schema_version").scalar_one()
                == SCHEMA_VERSION
            )
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            for table, count in before.items():
                assert (
                    connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
                    == count
                )
        edited = patch(client, stored, master_data={"container_number": "TEST-NEW"})
        assert edited["row_version"] == row["row_version"] + 1
        assert client.get("/api/v1/finance/invoices?q=TEST-MIGRATION").json()["items"][0] == invoice


def test_interrupted_version_three_upgrade_rolls_back_without_partial_schema(tmp_path):
    settings, path, row, _, _, before = previous_database(tmp_path)
    app = create_app(settings)

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("ALTER TABLE shipments ADD COLUMN master_data"):
            raise RuntimeError("Simulated interruption")

    event.listen(app.state.engine, "after_cursor_execute", interrupt)
    with pytest.raises(RuntimeError, match="Simulated interruption"), local_client(app):
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM local_schema_version").fetchone() == (3,)
        assert "master_data" not in [
            c[1] for c in connection.execute("PRAGMA table_info(shipments)")
        ]
        assert connection.execute("SELECT count(*) FROM reconciliation_logs").fetchone() == (
            before["reconciliation_logs"],
        )
        assert connection.execute("SELECT id FROM shipments").fetchone()[0] == row["id"].replace(
            "-", ""
        )
