"""End-to-end financial invariants against the migrated, restricted PostgreSQL role."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.finance import financial_json, safe_csv
from app.finance_schemas import InvoiceCreate
from tests.test_integration import create_shipment

pytest_plugins = ["tests.test_integration"]

D = Decimal


def api(e, method, path, data=None, role="finance", expected=200):
    response = getattr(e["client"], method)(
        "/api/v1/finance" + path,
        headers=e["headers"](role),
        **({"json": data} if data is not None else {}),
    )
    assert response.status_code == expected, response.text
    return (
        response.json()
        if "application/json" in response.headers.get("content-type", "")
        else response.text
    )


def provision(e, shipment, amount="500", month="2026-10-01", currency="USD", line=1, approve=True):
    api(e, "post", "/periods?period_month=" + month, expected=201)
    payload = dict(
        shipment_id=shipment["id"],
        supplier_id=str(e["supplier_id"]),
        charge_code="FREIGHT",
        line_no=line,
        month_accrued=month,
        amount=amount,
        extra_charges="0",
        currency=currency,
    )
    if not approve:
        # Preserve a legacy draft for historical-record compatibility cases.
        response = e["client"].post("/api/v1/provisions", headers=e["headers"]("one"), json=payload)
        assert response.status_code == 201, response.text
        return response.json()
    row = api(e, "post", "/provisions", payload, expected=201)
    if approve:
        row = api(
            e, "post", f"/provisions/{row['id']}/approve", {"expected_version": row["row_version"]}
        )
    return row


def invoice(e, shipment, amount="500", month="2026-10-01", number="F-001", **changes):
    payload = dict(
        supplier_id=str(e["supplier_id"]),
        company_code="JE_MX",
        invoice_number=number,
        issue_date="2026-10-10",
        accounting_period=month,
        currency="USD",
        lines=[
            dict(
                reference=shipment["reference_raw"],
                charge_code="FREIGHT",
                net_amount=amount,
                tax_amount="80",
            )
        ],
    )
    payload.update(changes)
    return api(e, "post", "/invoices", payload, expected=201)


def balances(e, month="2026-10-01", role="finance"):
    return api(e, "get", "/balances?month=" + month, role=role)


@pytest.mark.integration
def test_exact_invoice_closes_and_report_keeps_origin(environment):
    e = environment
    shipment = create_shipment(e)
    provision(e, shipment, month="2026-09-01")
    row = invoice(e, shipment)
    assert D(row["applied_amount"]) == 500 and D(row["pending_amount"]) == 0
    assert row["status"] == "APPROVED"
    balance = balances(e)["items"][0]
    assert balance["status"] == "CLOSED" and D(balance["closing_amount"]) == 0
    assert D(balance["opening_amount"]) == 500 and D(balance["released_amount"]) == 500
    before = balances(e, "2026-09-01")["items"][0]
    assert before["status"] == "OPEN" and D(before["closing_amount"]) == 500
    report = api(e, "get", "/report?month=2026-10-01")
    assert report["movements"][0]["month_accrued"] == "2026-09-01"
    assert not report["pending_invoices"]
    csv = api(e, "get", "/report.csv?month=2026-10-01")
    assert "F-001" in csv and "SALDO" in csv and "MATCH" in csv
    assert "500.0000" in csv


@pytest.mark.integration
def test_partial_and_no_invoice_roll_without_duplicate_provisions(environment):
    e = environment
    first = create_shipment(e)
    second = create_shipment(e)
    provision(e, first, month="2026-05-01")
    provision(e, second, month="2026-09-01")
    invoice(e, first, "300")
    rows = balances(e, "2026-11-01")
    assert rows["total"] == 2
    assert D(rows["totals"][0]["closing_amount"]) == 700
    assert {x["status"] for x in rows["items"]} == {"OPEN", "PARTIALLY_MATCHED"}
    assert all(D(x["new_amount"]) == 0 for x in rows["items"])


@pytest.mark.integration
def test_excess_is_not_negative_and_duplicate_invoice_rejected(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s)
    row = invoice(e, s, "600")
    assert D(row["pending_amount"]) == 100
    assert D(balances(e)["items"][0]["closing_amount"]) == 0
    pending = api(e, "get", "/report?month=2026-10-01")["pending_invoices"]
    assert D(pending[0]["amount"]) == 100
    payload = dict(
        supplier_id=str(e["supplier_id"]),
        company_code="JE_MX",
        invoice_number="f 001",
        issue_date="2026-10-10",
        accounting_period="2026-10-01",
        currency="USD",
        lines=[dict(reference=s["reference_raw"], charge_code="FREIGHT", net_amount="600")],
    )
    api(e, "post", "/invoices", payload, expected=409)


@pytest.mark.integration
def test_invoice_waits_for_approval_then_reconciles_once(environment):
    e = environment
    s = create_shipment(e)
    p = provision(e, s, approve=False)
    inv = invoice(e, s)
    assert D(inv["pending_amount"]) == 500
    api(e, "post", f"/provisions/{p['id']}/approve", {"expected_version": p["row_version"]})
    inv = api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        {"expected_version": inv["row_version"], "period_month": "2026-10-01"},
    )
    inv = api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        {"expected_version": inv["row_version"], "period_month": "2026-10-01"},
    )
    assert D(inv["applied_amount"]) == 500
    assert len(api(e, "get", "/report?month=2026-10-01")["movements"]) == 1


@pytest.mark.integration
def test_reversal_restores_balance_without_changing_prior_month(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s)
    inv = invoice(e, s)
    api(e, "post", "/periods?period_month=2026-11-01", expected=201)
    api(
        e,
        "post",
        f"/invoices/{inv['id']}/cancel",
        {
            "expected_version": inv["row_version"],
            "period_month": "2026-11-01",
            "reason": "Factura sustituida",
        },
    )
    october = balances(e)["items"][0]
    november = balances(e, "2026-11-01")["items"][0]
    assert D(october["closing_amount"]) == 0 and october["status"] == "CLOSED"
    assert D(november["closing_amount"]) == 500 and D(november["released_amount"]) == -500
    assert november["status"] == "OPEN"
    assert not api(e, "get", "/report?month=2026-11-01")["pending_invoices"]
    assert api(e, "get", "/report?month=2026-11-01")["movements"][0]["entry_type"] == "REVERSAL"


@pytest.mark.integration
def test_currency_and_charge_mismatch_never_consume_provision(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s, currency="MXN")
    inv = invoice(e, s)
    assert D(inv["pending_amount"]) == 500
    assert D(balances(e)["items"][0]["closing_amount"]) == 500
    provision(e, s, line=2)
    inv2 = invoice(
        e,
        s,
        number="F-002",
        lines=[dict(reference=s["reference_raw"], charge_code="BROKER", net_amount="500")],
    )
    assert D(inv2["pending_amount"]) == 500
    assert {x["currency"] for x in balances(e)["totals"]} == {"USD", "MXN"}


@pytest.mark.integration
def test_multi_reference_invoice_atomic_and_owner_scope(environment):
    e = environment
    a = create_shipment(e)
    b = create_shipment(e, "two")
    provision(e, a)
    provision(e, b)
    inv = invoice(
        e,
        a,
        lines=[
            dict(reference=a["reference_raw"], charge_code="FREIGHT", net_amount="200"),
            dict(reference=b["reference_raw"], charge_code="FREIGHT", net_amount="500"),
        ],
    )
    assert D(inv["applied_amount"]) == 700
    assert balances(e, role="one")["total"] == 1
    assert balances(e, role="two")["total"] == 1
    assert len(api(e, "get", "/report?month=2026-10-01", role="one")["movements"]) == 1
    api(e, "get", "/invoices", role="one", expected=403)
    api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        {"expected_version": inv["row_version"], "period_month": "2026-10-01"},
        role="manager",
        expected=403,
    )


@pytest.mark.integration
def test_audit_names_diffs_and_immutability(environment):
    e = environment
    s = create_shipment(e)
    response = e["client"].patch(
        "/api/v1/shipments/" + s["id"],
        headers=e["headers"]("one"),
        json={"expected_version": s["row_version"], "comments": "Nueva nota"},
    )
    assert response.status_code == 200
    entries = api(e, "get", "/history?action=SHIPMENT_UPDATED", role="one")["items"]
    assert entries[0]["actor_name"] == "one"
    assert entries[0]["changes"] == [{"field": "comments", "before": None, "after": "Nueva nota"}]
    assert api(e, "get", "/history", role="two")["total"] == 0
    provision(e, s)
    invoice(e, s)
    for table in ["reconciliation_logs", "reconciliation_allocations"]:
        with pytest.raises(DBAPIError), e["admin_engine"].begin() as connection:
            connection.execute(text(f"DELETE FROM {table}"))


@pytest.mark.integration
def test_invalid_reference_rolls_back_entire_invoice(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s)
    payload = dict(
        supplier_id=str(e["supplier_id"]),
        company_code="JE_MX",
        invoice_number="F-001",
        issue_date="2026-10-10",
        accounting_period="2026-10-01",
        currency="USD",
        lines=[
            dict(reference=s["reference_raw"], charge_code="FREIGHT", net_amount="100"),
            dict(reference="MISSING", charge_code="FREIGHT", net_amount="100"),
        ],
    )
    api(e, "post", "/invoices", payload, expected=422)
    assert api(e, "get", "/invoices")["total"] == 0
    assert D(balances(e)["items"][0]["closing_amount"]) == 500


@pytest.mark.integration
def test_later_period_movements_cannot_be_backdated(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s)
    api(e, "post", "/periods?period_month=2026-11-01", expected=201)
    invoice(e, s, "200", month="2026-11-01")
    payload = dict(
        supplier_id=str(e["supplier_id"]),
        company_code="JE_MX",
        invoice_number="F-002",
        issue_date="2026-10-10",
        accounting_period="2026-10-01",
        currency="USD",
        lines=[dict(reference=s["reference_raw"], charge_code="FREIGHT", net_amount="200")],
    )
    api(e, "post", "/invoices", payload, expected=409)
    assert api(e, "get", "/invoices")["total"] == 1


@pytest.mark.integration
def test_concurrent_invoices_cannot_overdraw(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoice, e, s, "400", number=f"F-{i}") for i in (1, 2)]
        rows = [f.result() for f in futures]
    assert sum(D(x["applied_amount"]) for x in rows) == 500
    assert sum(D(x["pending_amount"]) for x in rows) == 300
    assert D(balances(e)["items"][0]["closing_amount"]) == 0


def test_money_validation_and_exact_serialization():
    assert financial_json({"amount": D("99999999999999.1234")}) == {"amount": "99999999999999.1234"}
    assert safe_csv(" =HYPERLINK(1)").startswith("'")
    assert safe_csv(D("-500.0000")) == "-500.0000"
    for value in ["NaN", "Infinity", "-1", "0", "1.00001"]:
        with pytest.raises(ValueError):
            InvoiceCreate.model_validate(
                dict(
                    supplier_id="00000000-0000-0000-0000-000000000001",
                    company_code="X",
                    invoice_number="1",
                    issue_date="2026-10-01",
                    accounting_period="2026-10-01",
                    currency="USD",
                    lines=[dict(reference="X", charge_code="FREIGHT", net_amount=value)],
                )
            )


@pytest.mark.integration
def test_two_invoices_accumulate_and_fifo_keeps_each_origin(environment):
    e = environment
    s = create_shipment(e)
    provision(e, s, amount="200", month="2026-05-01")
    provision(e, s, amount="300", month="2026-09-01", line=2)
    invoice(e, s, amount="350")
    rows = balances(e)["items"]
    assert D(rows[0]["closing_amount"]) == 0
    assert D(rows[1]["closing_amount"]) == 150
    invoice(e, s, amount="150", number="F-002")
    assert D(balances(e)["totals"][0]["closing_amount"]) == 0
    assert len(api(e, "get", "/report?month=2026-10-01")["movements"]) == 3


@pytest.mark.integration
def test_closed_period_and_other_supplier_cannot_consume_balance(environment):
    from app.models import Supplier

    e = environment
    s = create_shipment(e)
    provision(e, s)
    with Session(e["admin_engine"]) as session:
        supplier = Supplier(code="OTHER", legal_name="Other supplier")
        session.add(supplier)
        session.commit()
        supplier_id = str(supplier.id)
    inv = invoice(e, s, supplier_id=supplier_id)
    assert D(inv["pending_amount"]) == 500
    with e["admin_engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE accounting_periods SET status='CLOSING', cutoff_at=now() WHERE period_month='2026-10-01'"
            )
        )
    api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        {"expected_version": inv["row_version"], "period_month": "2026-10-01"},
        expected=409,
    )
    assert D(balances(e)["items"][0]["closing_amount"]) == 500
