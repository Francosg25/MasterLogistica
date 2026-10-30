"""Optional departments and safe correction of the named master presets."""

import sqlite3
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.analysts import MASTER_ANALYST_CODES
from app.local_schema import LOCAL_SUPPLIER, LOCAL_USER, SCHEMA_VERSION
from app.main import create_app
from app.master_layouts import layout_code
from app.references import normalize_reference, parse_reference
from tests.test_local import local_client, local_settings

EXPECTED_CODES = {"MAG": 1, "ALEXA": 2, "DENI": 3, "ANDREA": 4, "NAT": 5}

BASE = dict(
    company_code="MXG",
    process_code="RM",
    operation_code="LI",
    reference_year=2026,
    business_unit="M01",
)


def create(client, **changes):
    response = client.post("/api/v1/shipments", json={**BASE, **changes})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("digits", ["1", "0001", "00001"])
@pytest.mark.parametrize("suffix", ["", ".DMR", ".PFA", ".CS1280", ".1", "-B"])
def test_department_free_historical_matching_keys_remain_literal(digits, suffix):
    raw = f"RM3-{digits}LI26-M23{suffix}"
    assert normalize_reference(raw) == raw
    assert normalize_reference(" " + raw.lower() + " ") == raw


@pytest.mark.parametrize("suffix", ["", ".DMR", ".PFA", ".CS1280"])
def test_optional_department_metadata_and_existing_padding_rule(suffix):
    row = parse_reference("RM3-0001LI26-M23" + suffix)
    assert row.department_code is None and row.sequence == 1
    assert row.is_current_format and row.base == "RM3-0001LI26-M23"
    assert row.normalized == row.base + suffix
    assert normalize_reference("RM3-1LI26-M23-MAT" + suffix) == "RM3-0001LI26-M23-MAT" + suffix
    assert normalize_reference("RM3-0001LI26-M23") != normalize_reference("RM3-0001LI26-M23-MAT")


@pytest.mark.parametrize("department", ["omitted", None, "", "MAT"])
def test_create_uses_optional_department_and_correct_owner_codes(tmp_path, department):
    with local_client(create_app(local_settings(tmp_path / "masters.db"))) as client:
        owners = client.get("/api/v1/masters/owners").json()
        assert {
            r["display_name"]: r["analyst_code"] for r in owners if r["analyst_code"] <= 5
        } == EXPECTED_CODES
        for owner in [r for r in owners if r["analyst_code"] <= 5]:
            payload = {} if department == "omitted" else {"department_code": department}
            row = create(client, owner_id=owner["id"], **payload)
            expected = f"RM{EXPECTED_CODES[owner['display_name']]}-0001LI26-M01"
            if department == "MAT":
                expected += "-MAT"
            assert row["reference_raw"] == expected
            assert row["department_code"] == ("MAT" if department == "MAT" else None)
            assert owner["layout_code"] == owner["display_name"]


def invoice_payload(number, lines):
    return dict(
        company_code="MXG",
        supplier_id=str(LOCAL_SUPPLIER),
        invoice_number=number,
        issue_date="2026-10-27",
        accounting_period="2026-10-01",
        currency="USD",
        lines=lines,
    )


def test_department_correction_preserves_two_distinct_references_and_financial_links(tmp_path):
    with local_client(create_app(local_settings(tmp_path / "financial.db"))) as client:
        bare = create(client, reference_raw="RM3-1LI26-M01")
        complete = create(client, reference_raw="RM3-0001LI26-M01-MAT", department_code="MAT")
        assert bare["reference_normalized"] == "RM3-1LI26-M01"
        lines = []
        for row, amount in [(bare, "100"), (complete, "200")]:
            response = client.post(
                "/api/v1/finance/provisions",
                json=dict(
                    shipment_id=row["id"],
                    supplier_id=str(LOCAL_SUPPLIER),
                    charge_code="FREIGHT",
                    provision_date="2026-10-27",
                    amount=amount,
                    extra_charges="0",
                    currency="USD",
                ),
            )
            assert response.status_code == 201, response.text
            lines.append(
                dict(
                    reference=row["reference_raw"],
                    charge_code="FREIGHT",
                    net_amount=amount,
                    tax_amount="0",
                )
            )
        response = client.post("/api/v1/finance/invoices", json=invoice_payload("REF-TEST", lines))
        assert response.status_code == 201, response.text
        invoice = response.json()
        assert {line["shipment_id"] for line in invoice["lines"]} == {bare["id"], complete["id"]}
        assert invoice["status"] == "APPROVED"
        assert Decimal(invoice["applied_amount"]) == 300
        assert Decimal(invoice["pending_amount"]) == 0
        for department in ["MAT", None]:
            response = client.patch(
                "/api/v1/shipments/" + bare["id"],
                json={"expected_version": bare["row_version"], "department_code": department},
            )
            assert response.status_code == 200, response.text
            changed = response.json()
            assert {
                key: changed[key]
                for key in ["id", "reference_raw", "reference_normalized", "normalization_version"]
            } == {
                key: bare[key]
                for key in ["id", "reference_raw", "reference_normalized", "normalization_version"]
            }
            bare = changed
        stored = client.get("/api/v1/finance/invoices?q=REF-TEST").json()["items"][0]
        assert stored["id"] == invoice["id"]
        assert [line["shipment_id"] for line in stored["lines"]] == [
            line["shipment_id"] for line in invoice["lines"]
        ]
        aliases = client.get("/api/v1/shipments/" + bare["id"] + "/identifiers").json()
        assert [item["normalized_value"] for item in aliases] == [bare["reference_normalized"]]


def legacy_database(tmp_path):
    path = tmp_path / "version-four.db"
    settings = local_settings(path)
    app = create_app(settings)
    with local_client(app) as client:
        owners = {r["display_name"]: r for r in client.get("/api/v1/masters/owners").json()}
        deni = create(client, reference_raw="RM1-0001LI26-M01-MAT", department_code="MAT")
        borrowed = create(client, owner_id=owners["NAT"]["id"], reference_raw="RM3-0075LI26-M19.1")
        response = client.patch(
            "/api/v1/shipments/" + borrowed["id"],
            json={"expected_version": 1, "reference_raw": "TEST-REFERENCE-CORRECTED"},
        )
        assert response.status_code == 200, response.text
        provision = client.post(
            "/api/v1/finance/provisions",
            json=dict(
                shipment_id=deni["id"],
                supplier_id=str(LOCAL_SUPPLIER),
                charge_code="FREIGHT",
                provision_date="2026-10-27",
                amount="100",
                extra_charges="0",
                currency="USD",
            ),
        )
        assert provision.status_code == 201, provision.text
        invoice = client.post(
            "/api/v1/finance/invoices",
            json=invoice_payload(
                "MIGRATION-TEST",
                [
                    dict(
                        reference=deni["reference_raw"],
                        charge_code="FREIGHT",
                        net_amount="100",
                        tax_amount="0",
                    ),
                ],
            ),
        )
        assert invoice.status_code == 201, invoice.text
        with app.state.engine.begin() as connection:
            # Recreate the exact earlier preset permutation, including its version marker.
            connection.execute(text("UPDATE users SET analyst_code = NULL"))
            for name, code in {"DENI": 1, "MAG": 2, "NAT": 3, "ANDREA": 4, "ALEXA": 5}.items():
                connection.execute(
                    text("UPDATE users SET analyst_code=:code WHERE display_name=:name"),
                    dict(code=code, name=name),
                )
            connection.execute(
                text("UPDATE reference_counters SET last_value=40 WHERE owner_id=:id"),
                {"id": LOCAL_USER.hex},
            )
            connection.execute(
                text("UPDATE shipments SET normalization_version='JE_REF_2026_10_V2'")
            )
            connection.exec_driver_sql("UPDATE local_schema_version SET version=4")
        old_row = client.get("/api/v1/shipments/" + deni["id"]).json()
    return settings, path, old_row


def snapshot(path):
    with sqlite3.connect(path) as connection:
        return {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY id").fetchall()
            for name in [
                "shipments",
                "shipment_identifiers",
                "provisions",
                "invoices",
                "invoice_lines",
                "reconciliation_allocations",
                "reconciliation_logs",
            ]
        }


def test_version_four_alignment_preserves_ids_records_audit_and_counter_history(tmp_path):
    settings, path, old_row = legacy_database(tmp_path)
    before = snapshot(path)
    app = create_app(settings)
    with local_client(app) as client:
        assert snapshot(path) == before
        assert client.get("/api/v1/shipments/" + old_row["id"]).json() == old_row
        owners = client.get("/api/v1/masters/owners").json()
        assert {
            o["display_name"]: o["analyst_code"]
            for o in owners
            if o["display_name"] in EXPECTED_CODES
        } == EXPECTED_CODES
        for owner in owners:
            assert owner["layout_code"] == owner["display_name"]
        generated = create(client)
        assert generated["reference_raw"] == "RM3-0076LI26-M01"
        mag = next(o for o in owners if o["display_name"] == "MAG")
        assert create(client, owner_id=mag["id"])["reference_raw"] == "RM1-0002LI26-M01"
        with app.state.engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert (
                connection.exec_driver_sql("SELECT version FROM local_schema_version").scalar_one()
                == SCHEMA_VERSION
            )
    with local_client(create_app(settings)) as client:
        assert create(client)["reference_raw"] == "RM3-0077LI26-M01"


def test_interrupted_alignment_rolls_back_codes_and_schema_version(tmp_path):
    settings, path, _ = legacy_database(tmp_path)
    before = snapshot(path)
    app = create_app(settings)

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE users SET analyst_code="):
            raise RuntimeError("Interrupted code alignment")

    event.listen(app.state.engine, "after_cursor_execute", interrupt)
    with pytest.raises(RuntimeError, match="Interrupted code alignment"), local_client(app):
        pass
    assert snapshot(path) == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM local_schema_version").fetchone() == (4,)
        assert dict(
            connection.execute(
                "SELECT display_name, analyst_code FROM users WHERE display_name IN ('DENI','MAG','NAT','ANDREA','ALEXA')"
            )
        ) == {
            "DENI": 1,
            "MAG": 2,
            "NAT": 3,
            "ANDREA": 4,
            "ALEXA": 5,
        }


def test_alignment_never_reassigns_an_unidentified_account(tmp_path):
    settings, path, _ = legacy_database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE users SET analyst_code=NULL WHERE analyst_code=1")
        connection.execute(
            "INSERT INTO users (id, entra_tenant_id, entra_object_id, email, display_name, role, is_active, analyst_code, row_version) VALUES (?,?,?,?,?,'OPERATOR',1,1,1)",
            (uuid4().hex, uuid4().hex, uuid4().hex, "test@example.com", "Otra cuenta"),
        )
        connection.commit()
    with pytest.raises(ValueError, match="otra cuenta"), local_client(create_app(settings)):
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT analyst_code FROM users WHERE display_name='Otra cuenta'"
        ).fetchone() == (1,)
        assert connection.execute("SELECT version FROM local_schema_version").fetchone() == (4,)


def test_earliest_local_account_keeps_its_id_records_and_counter(tmp_path):
    settings = local_settings(tmp_path / "first-version.db")
    app = create_app(settings)
    with local_client(app) as client:
        original = create(client, reference_raw="RM1-0001LI26-M01-MAT", department_code="MAT")
        with app.state.engine.begin() as connection:
            for statement in [
                "DELETE FROM reference_counters WHERE owner_id <> :id",
                "DELETE FROM users WHERE id <> :id",
                "UPDATE users SET display_name='Desarrollo local', analyst_code=1 WHERE id=:id",
                "UPDATE reference_counters SET last_value=123 WHERE owner_id=:id",
            ]:
                connection.execute(text(statement), {"id": LOCAL_USER.hex})
            connection.exec_driver_sql("UPDATE local_schema_version SET version=1")
    with local_client(create_app(settings)) as client:
        owners = client.get("/api/v1/masters/owners").json()
        assert {
            row["display_name"]: row["analyst_code"]
            for row in owners
            if row["display_name"] in EXPECTED_CODES
        } == EXPECTED_CODES
        assert next(row["id"] for row in owners if row["display_name"] == "DENI") == str(LOCAL_USER)
        assert client.get("/api/v1/shipments/" + original["id"]).json() == original
        assert create(client)["reference_raw"] == "RM3-0124LI26-M01"


def test_layout_fallback_uses_documented_codes():
    from types import SimpleNamespace

    assert MASTER_ANALYST_CODES == EXPECTED_CODES
    for name, code in EXPECTED_CODES.items():
        assert (
            layout_code(SimpleNamespace(display_name="Corporate account", analyst_code=code))
            == name
        )
