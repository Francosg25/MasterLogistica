from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Role = Literal["OPERATOR", "FINANCE", "MANAGER", "SUPER_ADMIN"]
Process = Literal["RM", "AF", "FG", "CR", "FA"]
Operation = Annotated[str, Field(min_length=1, max_length=100)]
Department = Literal["PRJ", "MAT", "QUA", "MAI", "HUM", "FIX", "RAW", "CTM", "SCR"]
ShipmentStatus = Annotated[str, Field(max_length=100)]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)]
ShortText = Annotated[str, Field(min_length=1, max_length=250)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


T = TypeVar("T")


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class VersionedRead(Schema):
    id: UUID
    row_version: int
    created_at: datetime
    updated_at: datetime


class UserRead(VersionedRead):
    entra_tenant_id: UUID
    entra_object_id: UUID
    email: str
    display_name: str
    role: Role
    is_active: bool
    analyst_code: int | None


class UserCreate(Schema):
    entra_object_id: UUID
    email: EmailStr
    display_name: Annotated[str, Field(min_length=1, max_length=150)]
    role: Role = "OPERATOR"
    analyst_code: Annotated[int, Field(ge=1, le=9)] | None = None
    last_reference_sequence: Annotated[int, Field(ge=0, le=2147483646)] = 0


class UserPatch(Schema):
    expected_version: Annotated[int, Field(ge=1)]
    email: EmailStr | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=150)] | None = None
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def no_null_updates(self):
        if any(
            getattr(self, name) is None for name in self.model_fields_set - {"expected_version"}
        ):
            raise ValueError("User fields cannot be cleared")
        return self


class SupplierRead(VersionedRead):
    code: str
    legal_name: str
    tax_id: str | None
    is_active: bool


class SupplierCreate(Schema):
    code: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Z0-9_-]+$")]
    legal_name: ShortText
    tax_id: Annotated[str, Field(max_length=40)] | None = None


class SupplierPatch(Schema):
    expected_version: Annotated[int, Field(ge=1)]
    legal_name: ShortText | None = None
    tax_id: Annotated[str, Field(max_length=40)] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def required_values(self):
        for name in self.model_fields_set & {"legal_name", "is_active"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be cleared")
        return self


class PeriodCreate(Schema):
    period_month: date

    @model_validator(mode="after")
    def first_day(self):
        if self.period_month.day != 1:
            raise ValueError("Accounting periods use the first day of the month")
        return self


class PeriodRead(PeriodCreate):
    status: str


class ShipmentCreate(Schema):
    owner_id: UUID | None = None
    company_code: Annotated[str, Field(min_length=1, max_length=32)]
    process_code: Process
    operation_code: Operation
    reference_year: Annotated[int, Field(ge=2000, le=2099)]
    business_unit: Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z0-9]{3}$")]
    department_code: Department
    status: ShipmentStatus = "DRAFT"
    ship_date: date | None = None
    eta: date | None = None
    delivery_date: date | None = None
    sender: ShortText | None = None
    origin: Annotated[str, Field(max_length=150)] | None = None
    consignee: ShortText | None = None
    destination: Annotated[str, Field(max_length=150)] | None = None
    carrier_broker_id: UUID | None = None
    shipping_line_id: UUID | None = None
    carrier_broker_name: Annotated[str, Field(max_length=250)] | None = None
    shipping_line_name: Annotated[str, Field(max_length=250)] | None = None
    plant_code: Annotated[str, Field(max_length=32)] | None = None
    comments: Annotated[str, Field(max_length=10000)] | None = None


class ShipmentPatch(Schema):
    expected_version: Annotated[int, Field(ge=1)]
    reference_raw: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    company_code: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    process_code: Process | None = None
    operation_code: Operation | None = None
    reference_year: Annotated[int, Field(ge=2000, le=2099)] | None = None
    business_unit: Annotated[str, Field(pattern=r"^[A-Z0-9]{3}$")] | None = None
    department_code: Department | None = None
    status: ShipmentStatus | None = None
    ship_date: date | None = None
    eta: date | None = None
    delivery_date: date | None = None
    sender: ShortText | None = None
    origin: Annotated[str, Field(max_length=150)] | None = None
    consignee: ShortText | None = None
    destination: Annotated[str, Field(max_length=150)] | None = None
    carrier_broker_id: UUID | None = None
    shipping_line_id: UUID | None = None
    carrier_broker_name: Annotated[str, Field(max_length=250)] | None = None
    shipping_line_name: Annotated[str, Field(max_length=250)] | None = None
    plant_code: Annotated[str, Field(max_length=32)] | None = None
    comments: Annotated[str, Field(max_length=10000)] | None = None
    damaged_material: bool | None = None
    expedited_status: Literal["NONE", "PENDING", "APPROVED"] | None = None
    pfa_approval_code: Annotated[str, Field(pattern=r"^CS[0-9]{1,32}$")] | None = None

    @model_validator(mode="after")
    def required_values(self):
        if any(
            getattr(self, n) is None
            for n in self.model_fields_set & {"status", "expedited_status", "company_code"}
        ):
            raise ValueError("Company and status cannot be cleared")
        return self


class ShipmentRead(VersionedRead):
    owner_id: UUID
    company_code: str
    reference_raw: str | None
    reference_normalized: str | None
    normalization_version: str | None
    process_code: str | None
    operation_code: str | None
    reference_year: int | None
    reference_sequence: int | None
    business_unit: str | None
    department_code: str | None
    transport_mode: str | None
    service_category: str
    direction: str
    status: str
    ship_date: date | None
    eta: date | None
    delivery_date: date | None
    sender: str | None
    origin: str | None
    consignee: str | None
    destination: str | None
    carrier_broker_id: UUID | None
    shipping_line_id: UUID | None
    carrier_broker_name: str | None
    shipping_line_name: str | None
    plant_code: str | None
    comments: str | None
    damaged_material: bool | None
    expedited_status: str
    pfa_approval_code: str | None


class IdentifierCreate(Schema):
    kind: Literal["AWB", "BL", "CONTAINER", "PEDIMENTO", "TRACKING"]
    raw_value: Annotated[str, Field(min_length=1, max_length=200)]


class IdentifierRead(Schema):
    id: UUID
    kind: str
    raw_value: str
    normalized_value: str
    normalization_version: str


class ProvisionCreate(Schema):
    shipment_id: UUID
    supplier_id: UUID
    charge_code: Literal["FREIGHT", "BROKER", "STORAGE"]
    line_no: Annotated[int, Field(ge=1, le=2147483647)] = 1
    provision_date: date | None = None
    month_accrued: date | None = None
    amount: Money | None = None
    extra_charges: Money | None = None
    currency: Literal["USD", "MXN"] | None = None
    usd_standard_cost: Money | None = None

    @model_validator(mode="after")
    def financial_values(self):
        if self.provision_date is not None:
            month = self.provision_date.replace(day=1)
            if self.month_accrued is not None and self.month_accrued != month:
                raise ValueError("La fecha de provisión debe pertenecer al mes de origen")
            self.month_accrued = month
        if self.month_accrued is None:
            raise ValueError("Captura la fecha de provisión")
        if self.month_accrued.day != 1:
            raise ValueError("Month accrued must be the first day of the month")
        validate_total(self.amount, self.extra_charges)
        return self


def validate_total(amount, extras):
    if amount is not None and extras is not None and amount + extras >= Decimal("100000000000000"):
        raise ValueError("Total amount exceeds the supported financial precision")


class ProvisionPatch(Schema):
    expected_version: Annotated[int, Field(ge=1)]
    amount: Money | None = None
    extra_charges: Money | None = None
    currency: Literal["USD", "MXN"] | None = None
    usd_standard_cost: Money | None = None


class ProvisionRead(VersionedRead):
    shipment_id: UUID
    supplier_id: UUID
    charge_code: str
    line_no: int
    month_accrued: date
    provision_date: date | None
    status: str
    amount: Decimal | None
    extra_charges: Decimal | None
    currency: str | None
    total_amount: Decimal | None
    usd_standard_cost: Decimal | None


class AuditRead(Schema):
    id: UUID
    shipment_id: UUID | None
    provision_id: UUID | None
    actor_user_id: UUID | None
    service_actor: str | None
    event_type: str
    occurred_at: datetime
    severity: str | None
    before_values: dict | None
    after_values: dict | None
    request_id: UUID | None


class ReferenceInput(Schema):
    raw_value: Annotated[str, Field(min_length=1, max_length=200)]
