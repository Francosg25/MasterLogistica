"""Exact settlement quantities in each original currency, independent of valuation."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.finance_schemas import SettlementFx

MONEY_TICK = Decimal("0.0001")
RATE_TICK = Decimal("0.0000000001")
FX_RULE = "REFERENCE_SETTLEMENT_FX_V1"


def invoice_fx(invoice):
    value = (invoice.source_data or {}).get("settlement_fx")
    return SettlementFx.model_validate(value) if value else None


def settlement_amounts(balance, remaining, provision_currency, invoice_currency, fx):
    """Return (released provision, applied invoice), capped in both currencies."""
    if provision_currency == invoice_currency:
        amount = min(balance, remaining)
        return amount, amount
    if fx is None:
        return Decimal(0), Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 60
        ratio = fx.mxn_per_usd if invoice_currency == "MXN" else Decimal(1) / fx.mxn_per_usd
        invoice_value = (balance * ratio).quantize(MONEY_TICK, rounding=ROUND_HALF_UP)
        if invoice_value <= remaining:
            return balance, invoice_value
        release = min(balance, (remaining / ratio).quantize(MONEY_TICK, rounding=ROUND_HALF_UP))
        return release, remaining


def allocation_fx(fx, provision_currency, invoice_currency):
    if provision_currency == invoice_currency or fx is None:
        return {}
    with localcontext() as ctx:
        ctx.prec = 50
        mxn_to_usd = (Decimal(1) / fx.mxn_per_usd).quantize(RATE_TICK, rounding=ROUND_HALF_UP)
    return dict(
        provision_fx_rate_to_usd=Decimal(1) if provision_currency == "USD" else mxn_to_usd,
        invoice_fx_rate_to_usd=Decimal(1) if invoice_currency == "USD" else mxn_to_usd,
        fx_evidence={
            **fx.model_dump(mode="json"),
            "basis": "SETTLEMENT",
            "provision_currency": provision_currency,
            "invoice_currency": invoice_currency,
            "rounding": "HALF_UP_4_DECIMALS",
        },
    )
