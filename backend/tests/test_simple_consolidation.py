"""One upload: source months, supplier registration and monthly balance evidence."""

import csv
import io
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice, Supplier
from tests.test_finance import api, provision
from tests.test_import_detection import invoice_row
from tests.test_integration import create_shipment
from tests.test_invoice_import import payload, workbook
from tests.test_local import local_financial_environment as local_financial_environment


def upload(rows):
    return payload(workbook(rows=rows), use_source_period=True, create_suppliers=True)


def test_consolidates_source_months_in_order_and_reports_historical_status(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="1200", month="2026-08-01")
    # Intentionally reverse order in workbook. September and October consume the same provision.
    data = upload(
        [
            invoice_row(shipment["reference_raw"], "OCTUBRE", number="OCT"),
            invoice_row(shipment["reference_raw"], number="SEP"),
        ]
    )
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["READY"] == 2
    api(
        e,
        "post",
        "/import/confirm",
        {**data, "selected": [g["key"] for g in preview["groups"]]},
        expected=201,
    )
    september = api(e, "get", "/report?month=2026-09-01")
    october = api(e, "get", "/report?month=2026-10-01")
    assert Decimal(september["balances"][0]["closing_amount"]) == 700
    assert Decimal(october["balances"][0]["closing_amount"]) == 200
    movement = september["movements"][0]
    assert movement["invoice_number"] == "SEP"
    assert movement["issue_date"] == "2026-09-10"
    assert movement["occurred_at"] and movement["period_month"] == "2026-09-01"
    assert movement["provision_status"] == "PARTIALLY_MATCHED"
    assert Decimal(movement["closing_amount"]) == 700
    assert movement["charge_code"] == "FREIGHT"
    report_csv = api(e, "get", "/report.csv?month=2026-09-01")
    rows = list(csv.DictReader(io.StringIO(report_csv.lstrip("\ufeff"))))
    applied = next(r for r in rows if r["Factura"] == "SEP")
    assert applied["Fecha factura"] == "2026-09-10"
    assert applied["Fecha aplicacion UTC"]
    assert Decimal(applied["Saldo provision al cierre"]) == 700
    assert all(None not in row for row in rows)


def test_new_supplier_is_created_only_on_confirm_and_reused(local_financial_environment):
    e = local_financial_environment
    shipment = create_shipment(e)
    data = upload([invoice_row(shipment["reference_raw"], supplier="New synthetic carrier")])
    with Session(e["runtime_engine"]) as session:
        before = session.scalar(select(func.count()).select_from(Supplier))
    preview = api(e, "post", "/import/preview", data)
    assert preview["groups"][0]["supplier_action"] == "NEW"
    assert preview["counts"]["READY"] == 1
    with Session(e["runtime_engine"]) as session:
        assert session.scalar(select(func.count()).select_from(Supplier)) == before
    api(
        e,
        "post",
        "/import/confirm",
        {**data, "selected": [preview["groups"][0]["key"]]},
        expected=201,
    )
    assert api(e, "post", "/import/preview", data)["counts"]["DUPLICATE"] == 1
    report_csv = api(e, "get", "/report.csv?month=2026-09-01")
    pending = next(csv.DictReader(io.StringIO(report_csv.lstrip("\ufeff"))))
    assert pending["Tipo"] == "UNPROVISIONED" and pending["Mes aplicacion"] == ""
    second = upload(
        [
            invoice_row(
                shipment["reference_raw"], supplier=" NEW SYNTHETIC CARRIER ", number="SECOND"
            )
        ]
    )
    preview = api(e, "post", "/import/preview", second)
    assert preview["groups"][0]["supplier_action"] == "MATCHED"
    api(
        e,
        "post",
        "/import/confirm",
        {**second, "selected": [preview["groups"][0]["key"]]},
        expected=201,
    )
    with Session(e["runtime_engine"]) as session:
        assert session.scalar(select(func.count()).select_from(Supplier)) == before + 1
        assert len(set(session.scalars(select(Invoice.supplier_id)))) == 1


def test_unknown_reference_does_not_create_supplier_or_invoice(local_financial_environment):
    e = local_financial_environment
    data = upload(
        [invoice_row("NOT-A-REGISTERED-REFERENCE", supplier="Do not create this supplier")]
    )
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["REVIEW"] == 1
    api(
        e,
        "post",
        "/import/confirm",
        {**data, "selected": [preview["groups"][0]["key"]]},
        expected=409,
    )
    with Session(e["runtime_engine"]) as session:
        assert (
            session.scalar(
                select(Supplier).where(Supplier.legal_name == "Do not create this supplier")
            )
            is None
        )
        assert session.scalar(select(func.count()).select_from(Invoice)) == 0


def test_inactive_or_ambiguous_supplier_is_not_silently_replaced(local_financial_environment):
    e = local_financial_environment
    shipment = create_shipment(e)
    with Session(e["runtime_engine"]) as session:
        session.add(Supplier(code="INACTIVE", legal_name="Inactive carrier", is_active=False))
        session.add_all(
            [
                Supplier(code="AMB-A", legal_name="Ambiguous carrier"),
                Supplier(code="AMB-B", legal_name="Ambiguous carrier"),
            ]
        )
        session.commit()
    for name in ("Inactive carrier", "Ambiguous carrier"):
        preview = api(
            e,
            "post",
            "/import/preview",
            upload([invoice_row(shipment["reference_raw"], supplier=name)]),
        )
        assert preview["counts"]["REVIEW"] == 1
        assert preview["groups"][0]["supplier_action"] == "REVIEW"


def test_multimonth_invoice_and_company_mismatch_still_need_review(local_financial_environment):
    e = local_financial_environment
    shipment = create_shipment(e)
    data = upload(
        [invoice_row(shipment["reference_raw"]), invoice_row(shipment["reference_raw"], "OCTUBRE")]
    )
    assert api(e, "post", "/import/preview", data)["counts"]["REVIEW"] == 1
    data = upload([invoice_row(shipment["reference_raw"], company="MXT")])
    assert api(e, "post", "/import/preview", data)["counts"]["REVIEW"] == 1


def test_invalid_selection_does_not_create_suppliers_or_invoices(local_financial_environment):
    e = local_financial_environment
    shipment = create_shipment(e)
    data = upload(
        [
            invoice_row(shipment["reference_raw"], number="VALID", supplier="Never committed"),
            invoice_row("MISSING", number="INVALID", supplier="Never committed"),
        ]
    )
    preview = api(e, "post", "/import/preview", data)
    api(
        e,
        "post",
        "/import/confirm",
        {**data, "selected": [g["key"] for g in preview["groups"]]},
        expected=409,
    )
    with Session(e["runtime_engine"]) as session:
        assert (
            session.scalar(select(Supplier).where(Supplier.legal_name == "Never committed")) is None
        )
        assert session.scalar(select(func.count()).select_from(Invoice)) == 0


def test_runtime_failure_rolls_back_new_supplier_with_the_batch(local_financial_environment):
    from tests.test_finance import invoice

    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="2000", month="2026-08-01")
    invoice(e, shipment, amount="100", number="ALREADY-OCTOBER")
    # September cannot consume a provision with a later October movement.
    data = upload(
        [
            invoice_row(
                shipment["reference_raw"], number="NEW-SUPPLIER", supplier="Rolled back carrier"
            ),
            invoice_row(shipment["reference_raw"], number="BACKDATED"),
        ]
    )
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["READY"] == 2
    api(
        e,
        "post",
        "/import/confirm",
        {**data, "selected": [g["key"] for g in preview["groups"]]},
        expected=409,
    )
    with Session(e["runtime_engine"]) as session:
        assert (
            session.scalar(select(Supplier).where(Supplier.legal_name == "Rolled back carrier"))
            is None
        )
        assert session.scalar(select(func.count()).select_from(Invoice)) == 1
