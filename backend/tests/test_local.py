"""Real local API/storage and the existing financial invariants on SQLite."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from app.auth import current_user
from app.config import Settings
from app.local_schema import LOCAL_SUPPLIER, LOCAL_TENANT, SCHEMA_VERSION
from app.main import create_app
from app.models import AccountingPeriod, Base, Provision, ReferenceCounter, Supplier, User
from tests import test_finance as finance_cases
from tests import test_invoice_import as import_cases


def local_settings(path, **changes):
    return Settings(
        _env_file=None,
        database_url=URL.create("sqlite+pysqlite", database=str(path)).render_as_string(
            hide_password=False
        ),
        **changes,
    )


def local_client(app, **changes):
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 40000), **changes)


def test_local_api_persists_edits_versions_and_reference_sequence(tmp_path):
    settings = local_settings(tmp_path / "master.db")
    first = create_app(settings)
    with local_client(first) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/v1/auth/config").json()["auth_mode"] == "development"
        assert client.get("/api/v1/auth/me").json()["role"] == "SUPER_ADMIN"
        assert client.get("/api/v1/references/catalogs").json()["master_access"]["can_edit"]
        payload = dict(
            company_code="LOCAL",
            process_code="RM",
            operation_code="SI",
            reference_year=2026,
            business_unit="M01",
            department_code="MAT",
        )
        response = client.post("/api/v1/shipments", json=payload)
        assert response.status_code == 201, response.text
        row = response.json()
        path = "/api/v1/shipments/" + row["id"]
        change = {"expected_version": row["row_version"], "comments": "Guardado local persistente"}
        response = client.patch(path, json=change)
        assert response.status_code == 200, response.text
        assert client.patch(path, json=change).status_code == 409
    with local_client(create_app(settings)) as client:
        assert client.get(path).json()["comments"] == change["comments"]
        assert client.get("/api/v1/shipments").json()["total"] == 1
        next_row = client.post("/api/v1/shipments", json=payload).json()
        assert next_row["reference_sequence"] == row["reference_sequence"] + 1
        history = client.get("/api/v1/finance/history?action=SHIPMENT_UPDATED").json()
        assert history["items"][0]["changes"][0]["after"] == change["comments"]


def test_local_all_master_fields_are_editable(local_financial_environment):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    row = create_shipment(e)
    changes = dict(
        reference_raw="Referencia manual / Norte 2026",
        company_code="MXT",
        business_unit="M46",
        operation_code="SI",
        process_code="AF",
        reference_year=2027,
        department_code="FIX",
        status="PLANNED",
        ship_date="2026-10-20",
        eta="2026-10-25",
        delivery_date="2026-10-27",
        sender="Proveedor editado",
        origin="Origen editado",
        consignee="Cliente editado",
        destination="Destino editado",
        plant_code="P2",
        carrier_broker_id=str(e["supplier_id"]),
        shipping_line_id=str(e["supplier_id"]),
        comments="Cambios completos desde el master",
    )
    path = "/api/v1/shipments/" + row["id"]
    response = e["client"].patch(
        path, headers=e["headers"]("one"), json={"expected_version": 1, **changes}
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["id"] == row["id"] and updated["row_version"] == 2
    assert {key: updated[key] for key in changes} == changes
    assert (updated["transport_mode"], updated["service_category"], updated["direction"]) == (
        "SEA",
        "FREIGHT",
        "I",
    )
    assert updated["reference_normalized"] == "REFERENCIAMANUAL/NORTE2026"
    assert e["client"].get(path, headers=e["headers"]("one")).json() == updated
    aliases = e["client"].get(path + "/identifiers", headers=e["headers"]("one")).json()
    assert {item["normalized_value"] for item in aliases} == {
        row["reference_normalized"],
        updated["reference_normalized"],
    }
    history = finance_cases.api(e, "get", "/history?action=SHIPMENT_UPDATED")["items"][0]
    assert {item["field"] for item in history["changes"]} >= {
        "reference_raw",
        "company_code",
        "business_unit",
        "operation_code",
    }


def test_local_reference_edits_keep_financial_links_and_allow_old_and_new_references(
    local_financial_environment,
):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    row = create_shipment(e)
    provision = finance_cases.provision(e, row)
    first_invoice = finance_cases.invoice(e, row, "100")
    response = e["client"].patch(
        "/api/v1/shipments/" + row["id"],
        headers=e["headers"]("one"),
        json={
            "expected_version": 1,
            "reference_raw": "REF / MANUAL 2026",
            "company_code": "MXT",
            "business_unit": "M19",
            "operation_code": "AI",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    second = finance_cases.invoice(e, updated, "200", number="F-002", company_code="MXT")
    third = finance_cases.invoice(
        e,
        {**updated, "reference_raw": row["reference_raw"]},
        "200",
        number="F-003",
        company_code="MXT",
    )
    assert Decimal(second["applied_amount"]) == Decimal(third["applied_amount"]) == 200
    old = next(
        item
        for item in finance_cases.api(e, "get", "/invoices")["items"]
        if item["id"] == first_invoice["id"]
    )
    assert old["lines"][0]["shipment_id"] == row["id"]
    balance = finance_cases.balances(e)["items"][0]
    assert balance["id"] == provision["id"] and balance["status"] == "CLOSED"
    assert Decimal(balance["closing_amount"]) == 0


def test_local_reference_corrections_reject_duplicates_without_partial_edits(
    local_financial_environment,
):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    first, second = create_shipment(e), create_shipment(e)
    renamed = e["client"].patch(
        "/api/v1/shipments/" + first["id"],
        headers=e["headers"]("one"),
        json={"expected_version": 1, "reference_raw": "REFERENCIA-CORREGIDA"},
    )
    assert renamed.status_code == 200, renamed.text
    path = "/api/v1/shipments/" + second["id"]
    for duplicate in ["referencia-corregida", first["reference_raw"]]:
        response = e["client"].patch(
            path,
            headers=e["headers"]("one"),
            json={"expected_version": 1, "reference_raw": duplicate, "company_code": "MXT"},
        )
        assert response.status_code == 422
        actual = e["client"].get(path, headers=e["headers"]("one")).json()
        assert actual["row_version"] == 1 and actual["company_code"] == second["company_code"]


def test_local_manual_reference_reserves_future_number_without_moving_counter_back(
    local_financial_environment,
):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    row = create_shipment(e)
    for version, number in [(1, 42), (2, 5)]:
        response = e["client"].patch(
            "/api/v1/shipments/" + row["id"],
            headers=e["headers"]("one"),
            json={"expected_version": version, "reference_raw": f"RM2-{number:04d}LI26-M23-MAT"},
        )
        assert response.status_code == 200, response.text
    assert create_shipment(e)["reference_sequence"] == 43


def test_local_optional_identity_cells_can_be_cleared_and_operation_reclassified(
    local_financial_environment,
):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    row = create_shipment(e)
    path = "/api/v1/shipments/" + row["id"]
    response = e["client"].patch(
        path,
        headers=e["headers"]("one"),
        json={
            "expected_version": 1,
            "reference_raw": None,
            "business_unit": None,
            "operation_code": None,
            "damaged_material": True,
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert (
        updated["reference_raw"]
        is updated["reference_normalized"]
        is updated["business_unit"]
        is updated["operation_code"]
        is None
    )
    assert (updated["transport_mode"], updated["service_category"], updated["direction"]) == (
        None,
        "FREIGHT",
        "N",
    )
    for changes in [{"business_unit": "M99"}, {"company_code": None}]:
        assert (
            e["client"]
            .patch(path, headers=e["headers"]("one"), json={"expected_version": 2, **changes})
            .status_code
            == 422
        )


def test_local_same_normalized_reference_without_existing_alias_is_saved_once(
    local_financial_environment,
):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    row = create_shipment(e)
    with e["admin_engine"].begin() as connection:
        connection.execute(text("DELETE FROM shipment_identifiers"))
    response = e["client"].patch(
        "/api/v1/shipments/" + row["id"],
        headers=e["headers"]("one"),
        json={
            "expected_version": 1,
            "reference_raw": row["reference_raw"].lower().replace("-", " - "),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["reference_normalized"] == row["reference_normalized"]


@pytest.fixture
def local_financial_environment(tmp_path):
    """Reuse corporate financial cases with real SQL and role checks, no Entra network."""
    settings = local_settings(
        tmp_path / "financial.db",
        company_codes=["JE_MX"],
        business_units={"M23": "Synthetic test unit"},
    )
    app = create_app(settings)
    with local_client(app) as client:
        rows = {}
        with app.state.session_factory() as session, session.begin():
            for name, role, code in [
                ("one", "OPERATOR", 2),
                ("two", "OPERATOR", 3),
                ("finance", "FINANCE", 4),
                ("manager", "MANAGER", None),
                ("admin", "SUPER_ADMIN", 5),
            ]:
                row = (
                    session.scalar(select(User).where(User.analyst_code == code)) if code else None
                )
                if row is None:
                    row = User(
                        id=uuid4(),
                        entra_tenant_id=LOCAL_TENANT,
                        entra_object_id=uuid4(),
                        email=f"{name}@example.com",
                        display_name=name,
                        role=role,
                        analyst_code=code,
                    )
                    session.add(row)
                else:
                    row.display_name, row.role = name, role
                session.flush()
                rows[name] = {"id": row.id}
                if code is not None and session.get(ReferenceCounter, row.id) is None:
                    session.add(ReferenceCounter(owner_id=row.id, last_value=0))
            supplier = session.get(Supplier, LOCAL_SUPPLIER)
            supplier.legal_name = "Example Test Carrier"
            session.add(AccountingPeriod(period_month=date(2026, 10, 1), status="OPEN"))

        def test_identity(request: Request):
            with app.state.session_factory() as session:
                return session.scalar(
                    select(User).where(User.id == rows[request.headers["X-Test-Role"]]["id"])
                )

        app.dependency_overrides[current_user] = test_identity
        yield dict(
            client=client,
            headers=lambda name: {"X-Test-Role": name},
            users=rows,
            supplier_id=LOCAL_SUPPLIER,
            admin_engine=app.state.engine,
            runtime_engine=app.state.engine,
            app=app,
        )


def test_local_saving_provision_opens_month_and_approves_once(local_financial_environment):
    from app.models import ReconciliationLog
    from tests.test_integration import create_shipment

    e = local_financial_environment
    shipment = create_shipment(e)
    payload = dict(
        shipment_id=shipment["id"],
        supplier_id=str(e["supplier_id"]),
        charge_code="FREIGHT",
        provision_date="2026-11-05",
        amount="500",
        extra_charges="0",
        currency="USD",
    )
    row = finance_cases.api(e, "post", "/provisions", payload, expected=201)
    assert row["status"] == "OPEN"
    with e["app"].state.session_factory() as session:
        stored = session.get(Provision, UUID(row["id"]))
        assert stored.approved_at is not None
        assert stored.approved_by_id == e["users"]["finance"]["id"]
        assert session.get(AccountingPeriod, date(2026, 11, 1)).status == "OPEN"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReconciliationLog)
                .where(
                    ReconciliationLog.provision_id == stored.id,
                    ReconciliationLog.event_type == "PROVISION_APPROVED",
                )
            )
            == 1
        )
    finance_cases.api(
        e, "post", f"/provisions/{row['id']}/approve", {"expected_version": row["row_version"]}
    )
    with e["app"].state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReconciliationLog)
                .where(
                    ReconciliationLog.provision_id == UUID(row["id"]),
                    ReconciliationLog.event_type == "PROVISION_APPROVED",
                )
            )
            == 1
        )
    balance = finance_cases.balances(e, "2026-11-01")["items"][0]
    assert balance["status"] == "OPEN" and Decimal(balance["closing_amount"]) == 500


def test_local_automatic_period_creation_rolls_back_invalid_provision_and_keeps_closed_month(
    local_financial_environment,
):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    shipment = create_shipment(e)
    payload = dict(
        shipment_id=shipment["id"],
        supplier_id=str(e["supplier_id"]),
        charge_code="FREIGHT",
        provision_date="2026-12-05",
        amount="0",
        extra_charges="0",
        currency="USD",
    )
    finance_cases.api(e, "post", "/provisions", payload, expected=422)
    with e["app"].state.session_factory() as session:
        assert session.get(AccountingPeriod, date(2026, 12, 1)) is None
    with e["admin_engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE accounting_periods SET status='CLOSING', cutoff_at=CURRENT_TIMESTAMP WHERE period_month='2026-10-01'"
            )
        )
    finance_cases.api(
        e,
        "post",
        "/provisions",
        {**payload, "provision_date": "2026-10-05", "amount": "500"},
        expected=409,
    )


def test_local_invoice_month_filter_and_automatic_month_creation(local_financial_environment):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    shipment = create_shipment(e)
    october = finance_cases.invoice(e, shipment, "100")
    november = finance_cases.invoice(e, shipment, "200", month="2026-11-01", number="F-NOV")
    assert [
        item["id"] for item in finance_cases.api(e, "get", "/invoices?month=2026-10-01")["items"]
    ] == [october["id"]]
    assert [
        item["id"] for item in finance_cases.api(e, "get", "/invoices?month=2026-11-01")["items"]
    ] == [november["id"]]
    finance_cases.api(e, "get", "/invoices?month=2026-11-02", expected=422)


FINANCIAL_CASES = [
    value
    for name, value in vars(finance_cases).items()
    if name.startswith("test_")
    and "environment" in value.__code__.co_varnames
    and "closed_period" not in name
]
IMPORT_CASES = [
    value
    for name, value in vars(import_cases).items()
    if name.startswith("test_")
    and "environment" in value.__code__.co_varnames
    and value.__code__.co_argcount == 1
]


@pytest.mark.parametrize("case", FINANCIAL_CASES + IMPORT_CASES, ids=lambda case: case.__name__)
def test_local_financial_invariants(local_financial_environment, case):
    case(local_financial_environment)


@pytest.mark.parametrize(
    "amount,month", [("300", "OCTUBRE"), ("0", "OCTUBRE"), ("300", "NOVIEMBRE")]
)
def test_local_import_collision(local_financial_environment, amount, month):
    import_cases.test_mapped_invoice_collision_never_imports_a_partial_group(
        local_financial_environment, amount, month
    )


def test_local_import_rollback(local_financial_environment, monkeypatch):
    import_cases.test_batch_failure_rolls_back_invoices_allocations_and_audit(
        local_financial_environment, monkeypatch
    )


def test_local_closed_period(local_financial_environment):
    e = local_financial_environment
    from tests.test_integration import create_shipment

    shipment = create_shipment(e)
    finance_cases.provision(e, shipment, amount="0.3000")
    first = finance_cases.invoice(e, shipment, amount="0.1000")
    second = finance_cases.invoice(e, shipment, amount="0.2000", number="F-002")
    assert Decimal(first["applied_amount"]) + Decimal(second["applied_amount"]) == Decimal("0.3000")
    assert Decimal(finance_cases.balances(e)["items"][0]["closing_amount"]) == 0
    with e["admin_engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE accounting_periods SET status='CLOSING', cutoff_at=CURRENT_TIMESTAMP WHERE period_month='2026-10-01'"
            )
        )
    finance_cases.api(
        e,
        "post",
        f"/invoices/{second['id']}/reconcile",
        {"expected_version": second["row_version"], "period_month": "2026-10-01"},
        expected=409,
    )


def test_local_exact_amounts_fx_and_large_aggregate(local_financial_environment):
    from tests.test_integration import create_shipment

    e = local_financial_environment
    shipment = create_shipment(e)
    for line in range(1, 12):
        finance_cases.provision(e, shipment, amount="99999999999999.1234", line=line, approve=False)
    with e["app"].state.session_factory() as session:
        total = session.scalar(select(func.sum(Provision.total_amount)))
        assert total == Decimal("1099999999999990.3574")
        row = session.scalar(select(Provision).limit(1))
        row.amount = Decimal("123.4567")
        row.currency = "MXN"
        row.fx_rate_to_usd = Decimal("0.0555555556")
        row.fx_rate_date = date(2026, 10, 1)
        row.fx_rate_source = "Prueba exacta"
        session.commit()
        session.refresh(row)
        assert row.total_usd == Decimal("6.8587")
        assert row.created_at.tzinfo is not None
    with pytest.raises(DBAPIError), e["admin_engine"].begin() as connection:
        connection.execute(text("UPDATE provisions SET fx_rate_to_usd='0.0000000000'"))
    with pytest.raises(DBAPIError), e["admin_engine"].begin() as connection:
        connection.execute(text("UPDATE provisions SET amount=0.1"))


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Host": "evil.example"},
        {"Host": "["},
        {"Forwarded": "for=127.0.0.1"},
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-Forwarded-Host": "127.0.0.1"},
    ],
)
def test_local_access_rejects_untrusted_headers(tmp_path, headers):
    with local_client(create_app(local_settings(tmp_path / "master.db"))) as client:
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 403


def test_local_access_rejects_remote_peer(tmp_path):
    app = create_app(local_settings(tmp_path / "master.db"))
    with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.10", 1234)) as client:
        assert client.get("/api/v1/auth/me").status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"app_env": "production"},
        {"auth_mode": "entra"},
        {"trusted_proxy_ips": ["127.0.0.1"]},
        {"allowed_hosts": ["*"]},
        {"allowed_origins": ["https://example.com"]},
    ],
)
def test_local_configuration_cannot_be_exposed_as_production(tmp_path, changes):
    with pytest.raises(ValidationError):
        local_settings(tmp_path / "master.db", **changes)


def test_local_startup_never_overwrites_an_unknown_database(tmp_path):
    import sqlite3

    path = tmp_path / "other.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE other_app (important TEXT)")
        connection.execute("INSERT INTO other_app VALUES ('conservar')")
    with (
        pytest.raises(ValueError, match="no pertenece"),
        local_client(create_app(local_settings(path))),
    ):
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT important FROM other_app").fetchone()[0] == "conservar"


def test_local_schema_requires_explicit_upgrade_without_reset(tmp_path):
    path = tmp_path / "master.db"
    settings = local_settings(path)
    app = create_app(settings)
    with local_client(app):
        with app.state.engine.begin() as connection:
            connection.execute(text("UPDATE local_schema_version SET version = 999"))
    with (
        pytest.raises(ValueError, match="actualización explícita"),
        local_client(create_app(settings)),
    ):
        pass


def test_local_initialization_preserves_postgresql_metadata(tmp_path):
    def ddl():
        return [
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
            for table in Base.metadata.sorted_tables
        ]

    before = ddl()
    with local_client(create_app(local_settings(tmp_path / "master.db"))):
        pass
    assert ddl() == before


def test_responsible_masters_manual_company_and_exact_provision_date(tmp_path):
    settings = local_settings(tmp_path / "masters.db")
    app = create_app(settings)
    with local_client(app) as client:
        owners = client.get("/api/v1/masters/owners").json()
        assert [o["display_name"] for o in owners] == ["DENI", "MAG", "NAT", "ANDREA", "ALEXA"]
        assert list(client.get("/api/v1/references/catalogs").json()["business_units"]) == [
            "M01",
            "M19",
            "M23",
            "M45",
            "M46",
        ]
        body = dict(
            company_code="MXG",
            process_code="RM",
            operation_code="SI",
            reference_year=2026,
            business_unit="M45",
            department_code="MAT",
        )
        rows = []
        for owner, operation in [(owners[0], "SI"), (owners[0], "AI"), (owners[1], "LI")]:
            response = client.post(
                "/api/v1/shipments",
                json={
                    **body,
                    "owner_id": owner["id"],
                    "operation_code": operation,
                },
            )
            assert response.status_code == 201, response.text
            rows.append(response.json())
        response = client.get("/api/v1/masters/shipments", params={"owner_id": owners[0]["id"]})
        assert {r["operation_code"] for r in response.json()["items"]} == {"SI", "AI"}
        assert response.json()["total"] == 2
        assert (
            client.get("/api/v1/masters/summary", params={"owner_id": owners[1]["id"]}).json()[
                "total"
            ]
            == 1
        )
        assert (
            client.post("/api/v1/shipments", json={**body, "business_unit": "T01"}).status_code
            == 422
        )
        assert "MXG" in client.get("/api/v1/references/catalogs").json()["company_codes"]
        references = client.get("/api/v1/finance/references").json()
        assert len(references) == 3
        assert references[0]["owner_name"] in {"DENI", "MAG"}
        client.post("/api/v1/finance/periods?period_month=2026-10-01")
        response = client.post(
            "/api/v1/finance/provisions",
            json={
                "shipment_id": rows[0]["id"],
                "supplier_id": str(LOCAL_SUPPLIER),
                "charge_code": "STORAGE",
                "provision_date": "2026-10-23",
                "amount": "125.5000",
                "extra_charges": "0",
                "currency": "USD",
            },
        )
        assert response.status_code == 201, response.text
        provision = response.json()
        assert provision["provision_date"] == "2026-10-23"
        assert provision["month_accrued"] == "2026-10-01"
    with local_client(create_app(settings)) as client:
        stored = client.get("/api/v1/provisions/" + provision["id"]).json()
        assert stored["provision_date"] == "2026-10-23"
        balance = client.get("/api/v1/finance/balances?month=2026-10-01").json()["items"][0]
        assert balance["provision_date"] == "2026-10-23"


def test_local_version_one_upgrade_preserves_provisions_without_inventing_a_day(tmp_path):
    settings = local_settings(tmp_path / "old.db")
    app = create_app(settings)
    with local_client(app) as client:
        shipment = client.post(
            "/api/v1/shipments",
            json=dict(
                company_code="MXT",
                process_code="RM",
                operation_code="LI",
                reference_year=2026,
                business_unit="M01",
                department_code="MAT",
            ),
        ).json()
        client.post("/api/v1/finance/periods?period_month=2026-10-01")
        provision = client.post(
            "/api/v1/finance/provisions",
            json=dict(
                shipment_id=shipment["id"],
                supplier_id=str(LOCAL_SUPPLIER),
                charge_code="BROKER",
                month_accrued="2026-10-01",
                currency="USD",
                amount="500",
                extra_charges="0",
            ),
        ).json()
        with app.state.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE provisions DROP COLUMN provision_date")
            connection.exec_driver_sql("UPDATE local_schema_version SET version = 1")
    with local_client(create_app(settings)) as client:
        row = client.get("/api/v1/provisions/" + provision["id"]).json()
        assert row["provision_date"] is None
        assert row["month_accrued"] == "2026-10-01"
        assert Decimal(row["amount"]) == 500


def test_local_manual_master_values_preserve_links_and_audit(local_financial_environment):
    from tests.master_cases import assert_manual_master_capture

    assert_manual_master_capture(local_financial_environment)


@pytest.fixture
def local_version_two_database(tmp_path, monkeypatch):
    from sqlalchemy import CheckConstraint, String

    from app import local_schema

    current_metadata = local_schema.local_metadata

    def previous_metadata():
        metadata = current_metadata()
        shipment = metadata.tables["shipments"]
        shipment.c.operation_code.type = String(2)
        shipment.c.status.type = String(24)
        shipment.append_constraint(
            CheckConstraint(
                "operation_code IS NULL OR operation_code IN ('AE','AI','SE','SI','LI','LE','PI','PE','VI','VE','A3','F4','F5','R1')",
                name="ck_shipment_operation",
            )
        )
        shipment.append_constraint(
            CheckConstraint(
                "status IN ('DRAFT','PLANNED','IN_TRANSIT','AT_PORT','CUSTOMS','DELIVERED','CANCELLED')",
                name="ck_shipment_status",
            )
        )
        return metadata

    path = tmp_path / "version-two.db"
    settings = local_settings(path)
    with monkeypatch.context() as patch:
        patch.setattr(local_schema, "SCHEMA_VERSION", 2)
        patch.setattr(local_schema, "local_metadata", previous_metadata)
        app = create_app(settings)
        with local_client(app) as client:
            shipment = client.post(
                "/api/v1/shipments",
                json=dict(
                    company_code="LOCAL",
                    process_code="RM",
                    operation_code="LI",
                    reference_year=2026,
                    business_unit="M01",
                    department_code="MAT",
                    status="CUSTOMS",
                    comments="Conservar este registro",
                ),
            ).json()
            provision = client.post(
                "/api/v1/finance/provisions",
                json=dict(
                    shipment_id=shipment["id"],
                    supplier_id=str(LOCAL_SUPPLIER),
                    charge_code="FREIGHT",
                    month_accrued="2026-10-01",
                    amount="500",
                    extra_charges="0",
                    currency="USD",
                ),
            ).json()
            with app.state.engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE shipments DROP COLUMN carrier_broker_name")
                connection.exec_driver_sql("ALTER TABLE shipments DROP COLUMN shipping_line_name")
                count = connection.exec_driver_sql(
                    "SELECT count(*) FROM reconciliation_logs"
                ).scalar_one()
    return settings, path, shipment, provision, count


def test_local_version_two_upgrade_preserves_financial_records(local_version_two_database):
    settings, _, shipment, provision, count = local_version_two_database
    app = create_app(settings)
    with local_client(app) as client:
        path = "/api/v1/shipments/" + shipment["id"]
        stored = client.get(path).json()
        assert stored["row_version"] == shipment["row_version"]
        assert (stored["operation_code"], stored["status"], stored["comments"]) == (
            "LI",
            "CUSTOMS",
            "Conservar este registro",
        )
        balance = client.get("/api/v1/finance/balances?month=2026-10-01").json()["items"][0]
        assert balance["id"] == provision["id"] and Decimal(balance["closing_amount"]) == 500
        with app.state.engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert (
                connection.exec_driver_sql("SELECT version FROM local_schema_version").scalar_one()
                == SCHEMA_VERSION
            )
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM reconciliation_logs").scalar_one()
                == count
            )
        response = client.patch(
            path,
            json={
                "expected_version": stored["row_version"],
                "operation_code": "LAND IMPO",
                "status": "En despacho",
                "carrier_broker_name": "Transportista manual",
            },
        )
        assert response.status_code == 200, response.text
    with local_client(create_app(settings)) as client:
        stored = client.get(path).json()
        assert (stored["operation_code"], stored["status"], stored["carrier_broker_name"]) == (
            "LAND IMPO",
            "En despacho",
            "Transportista manual",
        )


def test_local_version_two_upgrade_rolls_back_every_change(local_version_two_database, monkeypatch):
    import sqlite3

    from app import local_schema

    settings, path, _, _, _ = local_version_two_database
    upgrade = local_schema.upgrade_flexible_master

    def interrupted(connection):
        upgrade(connection)
        raise RuntimeError("Simular una interrupción de actualización")

    monkeypatch.setattr(local_schema, "upgrade_flexible_master", interrupted)
    with pytest.raises(RuntimeError, match="interrupción"), local_client(create_app(settings)):
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM local_schema_version").fetchone() == (2,)
        assert connection.execute("SELECT operation_code, status FROM shipments").fetchone() == (
            "LI",
            "CUSTOMS",
        )
        columns = {r[1] for r in connection.execute("PRAGMA table_info(shipments)")}
        assert "legacy_operation_code" not in columns and "carrier_broker_name" not in columns
