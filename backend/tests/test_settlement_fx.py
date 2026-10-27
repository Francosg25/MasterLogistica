"""Cross-currency quantities, frozen FX evidence, reversals and import compatibility."""

from decimal import Decimal as D

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance_schemas import SettlementFx
from app.models import ReconciliationAllocation as Allocation
from app.settlement_fx import settlement_amounts
from tests.test_finance import api, balances, invoice, provision
from tests.test_integration import create_shipment
from tests.test_invoice_import import payload, workbook
from tests.test_local import local_financial_environment as local_financial_environment

FX = dict(mxn_per_usd="20", rate_date="2026-10-27", source="Prueba sintética")


@pytest.mark.parametrize(
    "rate", ["0", "-20", "NaN", "Infinity", "10000000000", "0.0000000001", "20.12345678901"]
)
def test_invalid_exchange_rates_are_rejected(rate):
    with pytest.raises(ValidationError):
        SettlementFx(**{**FX, "mxn_per_usd": rate})


@pytest.mark.parametrize(
    "balance,remaining,pc,ic,expected",
    [
        ("680", "5600", "USD", "MXN", ("280.0000", "5600")),
        ("680", "13600", "USD", "MXN", ("680", "13600.0000")),
        ("680", "15000", "USD", "MXN", ("680", "13600.0000")),
        ("13600", "280", "MXN", "USD", ("5600.0000", "280")),
        ("13600", "680", "MXN", "USD", ("13600", "680.0000")),
        ("13600", "800", "MXN", "USD", ("13600", "680.0000")),
        ("1", "0.0001", "USD", "MXN", ("0.0000", "0.0001")),
    ],
)
def test_conversion_is_exact_and_capped_in_both_currencies(balance, remaining, pc, ic, expected):
    release, applied = settlement_amounts(D(balance), D(remaining), pc, ic, SettlementFx(**FX))
    assert (release, applied) == tuple(D(x) for x in expected)
    assert 0 <= release <= D(balance) and 0 <= applied <= D(remaining)


@pytest.mark.parametrize(
    "pc,ic,amount,bill,closing,pending",
    [
        ("USD", "MXN", "680", "5600", "400", "0"),
        ("USD", "MXN", "680", "13600", "0", "0"),
        ("USD", "MXN", "680", "15000", "0", "1400"),
        ("MXN", "USD", "13600", "280", "8000", "0"),
        ("MXN", "USD", "13600", "680", "0", "0"),
    ],
)
def test_cross_currency_updates_real_ledger_and_reports(
    local_financial_environment, pc, ic, amount, bill, closing, pending
):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount=amount, currency=pc)
    inv = invoice(e, shipment, amount=bill, currency=ic, fx=FX)
    assert D(inv["pending_amount"]) == D(pending)
    assert inv["fx"] == FX and inv["fx_required"] is False
    balance = balances(e)["items"][0]
    assert D(balance["closing_amount"]) == D(closing)
    assert balance["status"] == ("CLOSED" if D(closing) == 0 else "PARTIALLY_MATCHED")
    entry = inv["lines"][0]["applications"][0]
    assert entry["provision_currency"] == pc
    assert D(entry["provision_amount"]) == D(amount) - D(closing)
    assert D(entry["invoice_amount"]) == D(bill) - D(pending)
    report = api(e, "get", "/report?month=2026-10-01")
    movement = report["movements"][0]
    assert D(movement["provision_amount"]) == D(entry["provision_amount"])
    assert movement["provision_currency"] == pc and movement["currency"] == ic
    assert movement["fx"]["mxn_per_usd"] == "20"
    csv = api(e, "get", "/report.csv?month=2026-10-01")
    assert "MXN por USD" in csv and "Importe provision aplicado" in csv
    activity = api(e, "get", f"/references/{shipment['id']}/activity")
    assert activity["invoices"][0]["applications"] == inv["lines"][0]["applications"]


def test_old_pending_invoice_can_receive_fx_without_changing_original_amounts(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="680")
    inv = invoice(e, shipment, amount="5600", currency="MXN")
    assert inv["fx_required"] is True and D(inv["applied_amount"]) == 0
    updated = api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        dict(expected_version=inv["row_version"], period_month="2026-10-01", fx=FX),
    )
    assert updated["id"] == inv["id"] and updated["currency"] == "MXN"
    assert updated["net_amount"] == inv["net_amount"] and updated["tax_amount"] == inv["tax_amount"]
    assert updated["status"] == "APPROVED" and D(updated["applied_amount"]) == 5600
    assert D(balances(e)["items"][0]["closing_amount"]) == 400
    again = api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        dict(expected_version=updated["row_version"], period_month="2026-10-01", fx=FX),
    )
    assert again == updated
    api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        dict(
            expected_version=inv["row_version"],
            period_month="2026-10-01",
            fx={**FX, "mxn_per_usd": "25"},
        ),
        expected=409,
    )
    assert api(e, "get", "/invoices")["items"][0] == updated


def test_reversal_restores_both_original_currencies_and_the_original_rate(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="680")
    inv = invoice(e, shipment, amount="5600", currency="MXN", fx=FX)
    cancelled = api(
        e,
        "post",
        f"/invoices/{inv['id']}/cancel",
        dict(
            expected_version=inv["row_version"],
            period_month="2026-10-01",
            reason="Reversión sintética",
        ),
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["lines"][0]["applications"] == []
    assert D(balances(e)["items"][0]["closing_amount"]) == 680
    with Session(e["admin_engine"]) as session:
        entries = session.scalars(select(Allocation).order_by(Allocation.entry_type)).all()
        match, reverse = entries
        assert match.provision_release_amount == -reverse.provision_release_amount == 280
        assert match.invoice_allocated_amount == -reverse.invoice_allocated_amount == 5600
        assert match.provision_fx_rate_to_usd == reverse.provision_fx_rate_to_usd == D(1)
        assert match.invoice_fx_rate_to_usd == reverse.invoice_fx_rate_to_usd == D("0.05")
        assert match.fx_evidence == reverse.fx_evidence
        assert match.actual_usd == -reverse.actual_usd == 280


def test_import_keeps_usd_amount_and_original_peso_evidence(local_financial_environment):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="10000", currency="MXN")
    data = payload(workbook(reference=shipment["reference_raw"], usd="500"), fx=FX)
    preview = api(e, "post", "/import/preview", data)
    key = next(group["key"] for group in preview["groups"] if group["status"] == "READY")
    api(e, "post", "/import/confirm", {**data, "selected": [key]}, expected=201)
    inv = api(e, "get", "/invoices")["items"][0]
    assert inv["currency"] == "USD" and D(inv["net_amount"]) == 500
    assert inv["amount_basis"] == "USD_AMOUNT"
    assert inv["source_data"]["amount_basis"] == "USD_AMOUNT"
    assert inv["source_data"]["rows"][0]["source"]["CURRENCY"] == "MXN"
    assert D(balances(e)["items"][0]["closing_amount"]) == 0


def test_missing_rate_and_wrong_concept_do_not_consume_unrelated_balances(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="10000", currency="MXN")
    inv = invoice(e, shipment, amount="500")
    assert inv["fx_required"] is True
    other = invoice(
        e,
        shipment,
        number="BROKER-TEST",
        fx=FX,
        lines=[dict(reference=shipment["reference_raw"], charge_code="BROKER", net_amount="500")],
    )
    assert D(other["applied_amount"]) == 0
    assert D(balances(e)["items"][0]["closing_amount"]) == 10000


@pytest.mark.integration
def test_native_postgresql_cross_currency_quantities(environment):
    e = environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="680")
    inv = invoice(e, shipment, amount="5600", currency="MXN", fx=FX)
    assert D(inv["applied_amount"]) == 5600
    assert D(balances(e)["items"][0]["closing_amount"]) == 400


def test_new_rate_applies_only_to_pending_balance_and_preserves_previous_applications(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    provision(e, shipment, amount="100", line=1)
    inv = invoice(e, shipment, amount="4000", currency="MXN", fx=FX)
    assert D(inv["pending_amount"]) == 2000
    provision(e, shipment, amount="100", line=2)
    updated = api(
        e,
        "post",
        f"/invoices/{inv['id']}/reconcile",
        dict(
            expected_version=inv["row_version"],
            period_month="2026-10-01",
            fx={**FX, "mxn_per_usd": "25"},
        ),
    )
    assert D(updated["pending_amount"]) == 0
    applications = updated["lines"][0]["applications"]
    assert {a["fx"]["mxn_per_usd"]: D(a["provision_amount"]) for a in applications} == {
        "20": D(100),
        "25": D(80),
    }
    assert sum(D(b["closing_amount"]) for b in balances(e)["items"]) == 20
