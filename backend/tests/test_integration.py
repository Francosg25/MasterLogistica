"""Tests against disposable PostgreSQL. Never point these variables at an operational database."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.cli import bootstrap_admin
from app.main import create_app
from app.models import (
    AccountingPeriod,
    Base,
    ReferenceCounter,
    Shipment,
    Supplier,
    User,
)
from app.references import generate_reference
from tests.conftest import TENANT_ID

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database():
    runtime_url, admin_url = (
        os.environ.get("TEST_DATABASE_URL"),
        os.environ.get("TEST_ADMIN_DATABASE_URL"),
    )
    if not runtime_url or not admin_url:
        if os.environ.get("CI") == "true":
            pytest.fail("CI must configure the disposable PostgreSQL test database")
        pytest.skip(
            "Set TEST_DATABASE_URL and TEST_ADMIN_DATABASE_URL for isolated PostgreSQL integration tests"
        )
    runtime, admin = make_url(runtime_url), make_url(admin_url)
    if not runtime.database or not runtime.database.endswith("_test"):
        pytest.fail("Destructive test setup requires a database name ending in _test")
    if (runtime.database, runtime.host, runtime.port) != (admin.database, admin.host, admin.port):
        pytest.fail("Runtime and admin test connections must target the same database")
    if runtime.username != "masterlogistica_app" or admin.username == "masterlogistica_app":
        pytest.fail("Tests require separate restricted runtime and migration roles")
    admin_engine = create_engine(admin_url, hide_parameters=True)
    with admin_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": runtime_url,
        "MIGRATION_DATABASE_URL": admin_url,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
    )
    runtime_engine = create_engine(runtime_url, hide_parameters=True)
    yield admin_engine, runtime_engine, env
    runtime_engine.dispose()
    admin_engine.dispose()


@pytest.fixture
def environment(database, settings, rsa_key, token_factory):
    admin_engine, runtime_engine, _ = database
    tables = ", ".join('"' + name + '"' for name in Base.metadata.tables)
    with admin_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    rows = {}
    with Session(admin_engine) as session, session.begin():
        for name, role, code in [
            ("one", "OPERATOR", 1),
            ("two", "OPERATOR", 2),
            ("finance", "FINANCE", 3),
            ("manager", "MANAGER", None),
            ("admin", "SUPER_ADMIN", 4),
        ]:
            row = User(
                id=uuid4(),
                entra_tenant_id=TENANT_ID,
                entra_object_id=uuid4(),
                email=f"{name}@example.com",
                display_name=name,
                role=role,
                analyst_code=code,
                is_active=True,
            )
            session.add(row)
            session.flush()
            rows[name] = {"id": row.id, "oid": row.entra_object_id, "code": code}
            if code is not None:
                session.add(
                    ReferenceCounter(owner_id=row.id, last_value=1615 if name == "one" else 0)
                )
        supplier = Supplier(code="TEST", legal_name="Example Test Carrier")
        session.add(supplier)
        session.add(AccountingPeriod(period_month=date(2026, 10, 1), status="OPEN"))
        session.flush()
        supplier_id = supplier.id
    app = create_app(settings, lambda token: rsa_key.public_key())
    with TestClient(app) as client:

        def headers(name, **changes):
            return {"Authorization": "Bearer " + token_factory(rows[name]["oid"], changes=changes)}

        yield {
            "client": client,
            "headers": headers,
            "users": rows,
            "supplier_id": supplier_id,
            "admin_engine": admin_engine,
            "runtime_engine": runtime_engine,
            "app": app,
        }


def shipment_payload(**changes):
    return {
        "company_code": "JE_MX",
        "process_code": "RM",
        "operation_code": "LI",
        "reference_year": 2026,
        "business_unit": "M23",
        "department_code": "MAT",
        **changes,
    }


def create_shipment(e, name="one", **changes):
    response = e["client"].post(
        "/api/v1/shipments", headers=e["headers"](name), json=shipment_payload(**changes)
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_provision(e, shipment, name="one", **changes):
    data = {
        "shipment_id": shipment["id"],
        "supplier_id": str(e["supplier_id"]),
        "charge_code": "FREIGHT",
        "month_accrued": "2026-10-01",
        "amount": "100.1200",
        "extra_charges": "5.0000",
        "currency": "USD",
        **changes,
    }
    response = e["client"].post("/api/v1/provisions", headers=e["headers"](name), json=data)
    assert response.status_code == 201, response.text
    return response.json()


def test_migrations_up_down_and_no_model_drift(database):
    _, _, env = database
    cwd = Path(__file__).resolve().parents[1]
    for args in [("check",), ("downgrade", "base"), ("upgrade", "head"), ("check",)]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_real_postgresql_readiness(environment):
    assert environment["client"].get("/health/ready").status_code == 200


def test_owner_isolation_lists_detail_and_mutations(environment):
    e = environment
    one, two = create_shipment(e), create_shipment(e, "two", operation_code="AI")
    assert one["reference_normalized"] == "RM1-1616LI26-M23-MAT"
    assert one["owner_id"] == str(e["users"]["one"]["id"])
    assert two["transport_mode"] == "AIR"
    for name, total in [("one", 1), ("two", 1), ("finance", 0), ("manager", 2), ("admin", 2)]:
        response = e["client"].get("/api/v1/shipments", headers=e["headers"](name))
        assert response.status_code == 200 and response.json()["total"] == total
    path = "/api/v1/shipments/" + two["id"]
    for method, suffix, body in [
        ("GET", "", None),
        ("PATCH", "", {"expected_version": 1, "comments": "cross owner"}),
        ("GET", "/identifiers", None),
        ("POST", "/identifiers", {"kind": "BL", "raw_value": "123"}),
    ]:
        assert (
            e["client"]
            .request(method, path + suffix, headers=e["headers"]("one"), json=body)
            .status_code
            == 404
        )
    assert (
        e["client"]
        .post(
            "/api/v1/shipments",
            headers=e["headers"]("one"),
            json=shipment_payload(owner_id=two["owner_id"]),
        )
        .status_code
        == 422
    )
    assert (
        e["client"]
        .post("/api/v1/shipments", headers=e["headers"]("manager"), json=shipment_payload())
        .status_code
        == 403
    )
    assert (
        e["client"]
        .patch(
            path, headers=e["headers"]("manager"), json={"expected_version": 1, "comments": "edit"}
        )
        .status_code
        == 403
    )


def test_roles_claims_and_email_cannot_elevate_local_user(environment, token_factory):
    e = environment
    forged = e["headers"]("one", roles=["SUPER_ADMIN"], preferred_username="admin@example.com")
    assert e["client"].get("/api/v1/users", headers=forged).status_code == 403
    unknown = {
        "Authorization": "Bearer "
        + token_factory(uuid4(), changes={"preferred_username": "admin@example.com"})
    }
    assert e["client"].get("/api/v1/auth/me", headers=unknown).status_code == 403
    with e["admin_engine"].begin() as connection:
        connection.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"),
            {"id": e["users"]["one"]["id"]},
        )
    assert e["client"].get("/api/v1/auth/me", headers=e["headers"]("one")).status_code == 403


def test_stale_version_and_immutable_reference(environment):
    e = environment
    row = create_shipment(e)
    path = "/api/v1/shipments/" + row["id"]
    update = e["client"].patch(
        path, headers=e["headers"]("one"), json={"expected_version": 1, "status": "IN_TRANSIT"}
    )
    assert update.status_code == 200 and update.json()["row_version"] == 2
    assert (
        e["client"]
        .patch(path, headers=e["headers"]("one"), json={"expected_version": 1, "comments": "stale"})
        .status_code
        == 409
    )
    for key in [
        "owner_id",
        "reference_normalized",
        "process_code",
        "operation_code",
        "business_unit",
    ]:
        response = e["client"].patch(
            path, headers=e["headers"]("one"), json={"expected_version": 2, key: "change"}
        )
        assert response.status_code == 422


def test_dmr_pfa_aliases_do_not_change_base(environment):
    e = environment
    row = create_shipment(e)
    path = "/api/v1/shipments/" + row["id"]
    for version, changes in [
        (1, {"damaged_material": True}),
        (2, {"expedited_status": "PENDING"}),
        (3, {"expedited_status": "APPROVED", "pfa_approval_code": "CS1280"}),
    ]:
        response = e["client"].patch(
            path, headers=e["headers"]("one"), json={"expected_version": version, **changes}
        )
        assert response.status_code == 200, response.text
        assert response.json()["reference_normalized"] == row["reference_normalized"]
    aliases = e["client"].get(path + "/identifiers", headers=e["headers"]("one")).json()
    assert {r["normalized_value"] for r in aliases} == {
        row["reference_normalized"] + suffix for suffix in ["", ".DMR", ".PFA", ".CS1280"]
    }


def test_shared_bl_does_not_merge_shipments(environment):
    e = environment
    for name in ["one", "two"]:
        row = create_shipment(e, name)
        response = e["client"].post(
            "/api/v1/shipments/" + row["id"] + "/identifiers",
            headers=e["headers"](name),
            json={"kind": "BL", "raw_value": "001-234"},
        )
        assert response.status_code == 201 and response.json()["normalized_value"] == "001234"


def test_provisions_draft_precision_and_owner_isolation(environment):
    e = environment
    row = create_provision(e, create_shipment(e))
    assert row["status"] == "DRAFT" and Decimal(row["total_amount"]) == Decimal("105.12")
    path = "/api/v1/provisions/" + row["id"]
    assert e["client"].get(path, headers=e["headers"]("two")).status_code == 404
    assert (
        e["client"]
        .patch(path, headers=e["headers"]("two"), json={"expected_version": 1, "amount": "1"})
        .status_code
        == 404
    )
    assert e["client"].get("/api/v1/provisions", headers=e["headers"]("two")).json()["total"] == 0
    for key, value in [
        ("status", "OPEN"),
        ("month_accrued", "2026-11-01"),
        ("approved_by_id", str(uuid4())),
    ]:
        assert (
            e["client"]
            .patch(path, headers=e["headers"]("one"), json={"expected_version": 1, key: value})
            .status_code
            == 422
        )
    update = e["client"].patch(
        path, headers=e["headers"]("one"), json={"expected_version": 1, "amount": "99.9999"}
    )
    assert update.status_code == 200 and Decimal(update.json()["total_amount"]) == Decimal(
        "104.9999"
    )
    assert (
        e["client"]
        .patch(path, headers=e["headers"]("one"), json={"expected_version": 1, "amount": "1"})
        .status_code
        == 409
    )


def test_closed_period_blocks_provision_writes(environment):
    e = environment
    shipment = create_shipment(e)
    provision = create_provision(e, shipment)
    with e["admin_engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE accounting_periods SET status = 'CLOSING', cutoff_at = now() WHERE period_month = '2026-10-01'"
            )
        )
    response = e["client"].patch(
        "/api/v1/provisions/" + provision["id"],
        headers=e["headers"]("one"),
        json={"expected_version": 1, "amount": "1"},
    )
    assert response.status_code == 409
    data = {
        "shipment_id": shipment["id"],
        "supplier_id": str(e["supplier_id"]),
        "charge_code": "EXTRA",
        "month_accrued": "2026-10-01",
    }
    assert (
        e["client"].post("/api/v1/provisions", headers=e["headers"]("one"), json=data).status_code
        == 409
    )


def test_admin_user_provisioning_and_last_admin_guard(environment):
    e = environment
    data = {
        "entra_object_id": str(uuid4()),
        "email": "new@example.com",
        "display_name": "New Operator",
        "analyst_code": 5,
        "last_reference_sequence": 100,
    }
    response = e["client"].post("/api/v1/users", headers=e["headers"]("admin"), json=data)
    assert response.status_code == 201, response.text
    assert (
        e["client"].post("/api/v1/users", headers=e["headers"]("admin"), json=data).status_code
        == 409
    )
    path = "/api/v1/users/" + str(e["users"]["admin"]["id"])
    assert (
        e["client"]
        .patch(
            path, headers=e["headers"]("admin"), json={"expected_version": 1, "role": "OPERATOR"}
        )
        .status_code
        == 409
    )
    assert (
        e["client"]
        .patch(
            path, headers=e["headers"]("admin"), json={"expected_version": 1, "is_active": False}
        )
        .status_code
        == 409
    )


def test_audit_is_scoped_and_immutable_even_for_migration_role(environment):
    e = environment
    one = create_shipment(e)
    create_shipment(e, "two")
    logs = e["client"].get("/api/v1/audit", headers=e["headers"]("one")).json()
    assert logs["total"] == 1 and logs["items"][0]["shipment_id"] == one["id"]
    event_id = logs["items"][0]["id"]
    for statement in [
        "UPDATE reconciliation_logs SET event_type = 'TAMPERED' WHERE id = :id",
        "DELETE FROM reconciliation_logs WHERE id = :id",
    ]:
        with pytest.raises(DBAPIError):
            with e["admin_engine"].begin() as connection:
                connection.execute(text(statement), {"id": event_id})


def test_restricted_database_role_has_no_delete_or_financial_release_privileges(environment):
    with environment["runtime_engine"].connect() as connection:
        for table, privilege, expected in [
            ("shipments", "SELECT", True),
            ("shipments", "INSERT", True),
            ("shipments", "DELETE", False),
            ("reconciliation_logs", "INSERT", True),
            ("reconciliation_logs", "UPDATE", False),
            ("reconciliation_logs", "TRUNCATE", False),
            ("invoices", "INSERT", False),
            ("reconciliation_allocations", "INSERT", False),
            ("provision_periods", "INSERT", False),
            ("alembic_version", "UPDATE", False),
        ]:
            assert (
                connection.scalar(
                    text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                    {"table": table, "privilege": privilege},
                )
                is expected
            )


def test_reference_counter_concurrency_and_rollback(environment):
    e = environment
    owner_id = e["users"]["one"]["id"]

    def generate(commit=True):
        with Session(e["runtime_engine"]) as session:
            user = session.get(User, owner_id)
            reference, sequence = generate_reference(
                session,
                user,
                process="RM",
                operation="LI",
                year=2026,
                business_unit="M23",
                department="MAT",
            )
            if commit:
                session.commit()
            else:
                session.rollback()
            return reference, sequence

    rolled = generate(False)
    next_row = generate()
    assert rolled == next_row
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda i: generate(), range(12)))
    assert len({row[0] for row in rows}) == 12
    assert sorted(row[1] for row in rows) == list(range(1617, 1629))


def test_audit_failure_rolls_back_operation_and_counter(environment):
    e = environment
    with e["admin_engine"].begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION test_reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test audit failure'; END $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER test_audit_failure BEFORE INSERT ON reconciliation_logs FOR EACH ROW EXECUTE FUNCTION test_reject_audit()"
            )
        )
    try:
        response = e["client"].post(
            "/api/v1/shipments", headers=e["headers"]("one"), json=shipment_payload()
        )
        assert response.status_code == 503
        with e["admin_engine"].connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Shipment)) == 0
            assert (
                connection.scalar(
                    select(ReferenceCounter.last_value).where(
                        ReferenceCounter.owner_id == e["users"]["one"]["id"]
                    )
                )
                == 1615
            )
    finally:
        with e["admin_engine"].begin() as connection:
            connection.execute(text("DROP TRIGGER test_audit_failure ON reconciliation_logs"))
            connection.execute(text("DROP FUNCTION test_reject_audit()"))


def test_bootstrap_refuses_restricted_role_and_existing_admin(environment, settings):
    with pytest.raises(ValueError, match="separate migration"):
        bootstrap_admin(settings, uuid4(), "bootstrap@example.com", "Bootstrap")
    admin_settings = settings.model_copy(
        update={
            "migration_database_url": settings.database_url.__class__(
                os.environ["TEST_ADMIN_DATABASE_URL"]
            )
        }
    )
    with pytest.raises(ValueError, match="already exists"):
        bootstrap_admin(admin_settings, uuid4(), "bootstrap@example.com", "Bootstrap")
