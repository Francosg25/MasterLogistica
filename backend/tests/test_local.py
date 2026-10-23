"""Real local API/storage and the existing financial invariants on SQLite."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

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
from app.local_schema import LOCAL_SUPPLIER, LOCAL_TENANT
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
            business_unit="T01",
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
                session.flush()
                rows[name] = {"id": row.id}
                if code is not None:
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
