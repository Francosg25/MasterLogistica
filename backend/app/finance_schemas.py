"""Financial commands use decimal money and explicit accounting months."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas import Money, Schema, validate_total


class VersionCommand(Schema):
    expected_version: Annotated[int, Field(ge=1)]


class InvoiceLineCreate(Schema):
    reference: Annotated[str, Field(min_length=1, max_length=160)]
    charge_code: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Z0-9_-]+$")]
    description: Annotated[str, Field(max_length=1000)] = ""
    net_amount: Money
    tax_amount: Money = 0

    @model_validator(mode="after")
    def positive(self):
        if self.net_amount <= 0:
            raise ValueError("El importe neto debe ser mayor que cero")
        validate_total(self.net_amount, self.tax_amount)
        return self


class InvoiceCreate(Schema):
    supplier_id: UUID
    company_code: Annotated[str, Field(min_length=1, max_length=32)]
    invoice_number: Annotated[str, Field(min_length=1, max_length=120)]
    issue_date: date
    accounting_period: date
    currency: Literal["USD", "MXN"]
    lines: Annotated[list[InvoiceLineCreate], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def valid_month(self):
        if self.accounting_period.day != 1:
            raise ValueError("El periodo debe ser el primer día del mes")
        validate_total(sum(x.net_amount for x in self.lines), sum(x.tax_amount for x in self.lines))
        return self


class ReconcileCommand(VersionCommand):
    period_month: date

    @model_validator(mode="after")
    def valid_month(self):
        if self.period_month.day != 1:
            raise ValueError("El periodo debe ser el primer día del mes")
        return self


class CancelInvoice(ReconcileCommand):
    reason: Annotated[str, Field(min_length=3, max_length=1000)]
