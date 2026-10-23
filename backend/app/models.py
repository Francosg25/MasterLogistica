"""Shared SQLAlchemy entities and invariants for MasterLogistica.

PostgreSQL production schema is versioned by Alembic. The local development
schema is initialized separately with SQLite-compatible types and constraints.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB as PostgresJSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.storage_types import ExactNumeric as Numeric
from app.storage_types import UTCDateTime as DateTime

JSONB = JSON().with_variant(PostgresJSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )


class VersionedMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls):
        # Protege escrituras ORM individuales. Operaciones bulk requieren controles explícitos.
        return {"version_id_col": cls.row_version}


def finite_check(name: str, *columns: str, nonnegative: bool = False):
    predicates = []
    for column in columns:
        bounds = f" AND {column} >= 0" if nonnegative else ""
        predicates.append(f"({column} IS NULL OR ({column} <> 'NaN'::numeric{bounds}))")
    return CheckConstraint(" AND ".join(predicates), name=name)


class User(IdentityMixin, VersionedMixin, Base):
    __tablename__ = "users"
    entra_tenant_id: Mapped[UUID] = mapped_column(Uuid)
    entra_object_id: Mapped[UUID] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(254))
    display_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(24), server_default="OPERATOR")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    analyst_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    __table_args__ = (
        UniqueConstraint("entra_tenant_id", "entra_object_id", name="uq_users_entra_identity"),
        CheckConstraint(
            "role IN ('OPERATOR','FINANCE','MANAGER','SUPER_ADMIN')", name="ck_users_role"
        ),
        CheckConstraint("row_version > 0", name="ck_users_version"),
        CheckConstraint(
            "analyst_code IS NULL OR analyst_code BETWEEN 1 AND 9", name="ck_users_analyst_code"
        ),
    )


class ReferenceCounter(Base):
    __tablename__ = "reference_counters"
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    last_value: Mapped[int] = mapped_column(Integer, server_default="0")
    __table_args__ = (CheckConstraint("last_value >= 0", name="ck_reference_counter_positive"),)


class Supplier(IdentityMixin, VersionedMixin, Base):
    __tablename__ = "suppliers"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    legal_name: Mapped[str] = mapped_column(String(250))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class AccountingPeriod(Base):
    __tablename__ = "accounting_periods"
    period_month: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(12), server_default="OPEN")
    cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    __table_args__ = (
        CheckConstraint("EXTRACT(DAY FROM period_month) = 1", name="ck_period_month_first_day"),
        CheckConstraint("status IN ('OPEN','CLOSING','CLOSED')", name="ck_period_status"),
        CheckConstraint("status = 'OPEN' OR cutoff_at IS NOT NULL", name="ck_period_cutoff"),
        CheckConstraint(
            "(status = 'CLOSED' AND closed_at IS NOT NULL AND closed_by_id IS NOT NULL AND cutoff_at IS NOT NULL) "
            "OR (status <> 'CLOSED' AND closed_at IS NULL AND closed_by_id IS NULL)",
            name="ck_period_closure",
        ),
    )


class Shipment(IdentityMixin, VersionedMixin, Base):
    __tablename__ = "shipments"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    company_code: Mapped[str] = mapped_column(String(32))
    legacy_sec: Mapped[str | None] = mapped_column(String(40))
    reference_raw: Mapped[str | None] = mapped_column(String(160))
    reference_normalized: Mapped[str | None] = mapped_column(String(160))
    normalization_version: Mapped[str | None] = mapped_column(String(32))
    process_code: Mapped[str | None] = mapped_column(String(2))
    operation_code: Mapped[str | None] = mapped_column(String(100))
    reference_year: Mapped[int | None] = mapped_column(Integer)
    reference_sequence: Mapped[int | None] = mapped_column(Integer)
    department_code: Mapped[str | None] = mapped_column(String(3))
    expedited_status: Mapped[str] = mapped_column(String(12), server_default="NONE")
    pfa_approval_code: Mapped[str | None] = mapped_column(String(40))
    transport_mode: Mapped[str | None] = mapped_column(String(16))
    service_category: Mapped[str] = mapped_column(String(16), server_default="FREIGHT")
    direction: Mapped[str] = mapped_column(String(1))
    status: Mapped[str] = mapped_column(String(100), server_default="DRAFT")
    ship_date: Mapped[date | None] = mapped_column(Date)
    eta: Mapped[date | None] = mapped_column(Date)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    sender: Mapped[str | None] = mapped_column(String(250))
    origin: Mapped[str | None] = mapped_column(String(150))
    consignee: Mapped[str | None] = mapped_column(String(250))
    destination: Mapped[str | None] = mapped_column(String(150))
    carrier_broker_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    shipping_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    carrier_broker_name: Mapped[str | None] = mapped_column(String(250))
    shipping_line_name: Mapped[str | None] = mapped_column(String(250))
    plant_code: Mapped[str | None] = mapped_column(String(32))
    business_unit: Mapped[str | None] = mapped_column(String(32))
    scs_security_status: Mapped[str | None] = mapped_column(String(64))
    damaged_material: Mapped[bool | None] = mapped_column(Boolean)
    comments: Mapped[str | None] = mapped_column(Text)
    arrival_port: Mapped[str | None] = mapped_column(String(150))
    vessel: Mapped[str | None] = mapped_column(String(150))
    etd_origin_port: Mapped[date | None] = mapped_column(Date)
    actual_departure_port: Mapped[date | None] = mapped_column(Date)
    eta_arrival_port: Mapped[date | None] = mapped_column(Date)
    actual_arrival_port: Mapped[date | None] = mapped_column(Date)
    customs_appointment: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    haulage_type: Mapped[str | None] = mapped_column(String(80))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    package_count: Mapped[int | None] = mapped_column(Integer)
    piece_count: Mapped[int | None] = mapped_column(Integer)
    export_invoice_reference: Mapped[str | None] = mapped_column(String(160))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    __table_args__ = (
        CheckConstraint(
            "transport_mode IS NULL OR transport_mode IN ('AIR','SEA','LAND','MULTIMODAL')",
            name="ck_shipment_mode",
        ),
        CheckConstraint(
            "service_category IN ('FREIGHT','COURIER','COMPLIANCE')", name="ck_shipment_service"
        ),
        CheckConstraint("direction IN ('I','O','N')", name="ck_shipment_direction"),
        CheckConstraint(
            "reference_normalized IS NULL OR (reference_raw IS NOT NULL AND normalization_version IS NOT NULL AND length(btrim(reference_normalized)) > 0)",
            name="ck_shipment_reference",
        ),
        CheckConstraint("package_count IS NULL OR package_count >= 0", name="ck_shipment_packages"),
        CheckConstraint("piece_count IS NULL OR piece_count >= 0", name="ck_shipment_pieces"),
        finite_check("ck_shipment_weight", "weight_kg", nonnegative=True),
        CheckConstraint("row_version > 0", name="ck_shipment_version"),
        UniqueConstraint("reference_normalized", name="uq_shipments_reference_normalized"),
        CheckConstraint(
            "process_code IS NULL OR process_code IN ('RM','AF','FG','DR','CR','FA')",
            name="ck_shipment_process",
        ),
        CheckConstraint(
            "department_code IS NULL OR department_code IN ('PRJ','MAT','QUA','MAI','HUM','FIX','RAW','CTM','SCR')",
            name="ck_shipment_department",
        ),
        CheckConstraint(
            "reference_year IS NULL OR reference_year BETWEEN 2000 AND 2099",
            name="ck_shipment_reference_year",
        ),
        CheckConstraint(
            "reference_sequence IS NULL OR reference_sequence > 0", name="ck_shipment_sequence"
        ),
        CheckConstraint(
            "expedited_status IN ('NONE','PENDING','APPROVED')", name="ck_shipment_expedited"
        ),
        CheckConstraint(
            "(expedited_status = 'APPROVED' AND pfa_approval_code IS NOT NULL) OR (expedited_status <> 'APPROVED' AND pfa_approval_code IS NULL)",
            name="ck_shipment_pfa_code",
        ),
        Index("ix_shipments_owner_ship_date", "owner_id", "ship_date"),
        Index("ix_shipments_company_reference", "company_code", "reference_normalized"),
    )


class ShipmentIdentifier(IdentityMixin, Base):
    __tablename__ = "shipment_identifiers"
    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20))
    raw_value: Mapped[str] = mapped_column(String(200))
    normalized_value: Mapped[str] = mapped_column(String(200))
    normalization_version: Mapped[str] = mapped_column(String(32))
    __table_args__ = (
        CheckConstraint(
            "kind IN ('REFERENCE','AWB','BL','CONTAINER','PEDIMENTO','TRACKING')",
            name="ck_shipment_identifier_kind",
        ),
        CheckConstraint("length(btrim(normalized_value)) > 0", name="ck_shipment_identifier_value"),
        UniqueConstraint("shipment_id", "kind", "normalized_value", name="uq_shipment_identifier"),
        Index("ix_shipment_identifiers_lookup", "kind", "normalized_value"),
    )


class Provision(IdentityMixin, VersionedMixin, Base):
    __tablename__ = "provisions"
    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id", ondelete="RESTRICT"))
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    charge_code: Mapped[str] = mapped_column(String(40))
    line_no: Mapped[int] = mapped_column(Integer)
    provision_date: Mapped[date | None] = mapped_column(Date)
    month_accrued: Mapped[date] = mapped_column(
        ForeignKey("accounting_periods.period_month", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), server_default="DRAFT")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    extra_charges: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    total_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        Computed("amount + extra_charges", persisted=True),
    )
    usd_standard_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    fx_rate_to_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    fx_rate_date: Mapped[date | None] = mapped_column(Date)
    fx_rate_source: Mapped[str | None] = mapped_column(String(100))
    total_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        Computed("(amount + extra_charges) * fx_rate_to_usd", persisted=True),
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_period: Mapped[date | None] = mapped_column(
        ForeignKey("accounting_periods.period_month", ondelete="RESTRICT")
    )
    terminal_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    terminal_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            "shipment_id", "supplier_id", "charge_code", "line_no", name="uq_provision_cost_line"
        ),
        CheckConstraint("line_no > 0", name="ck_provision_line"),
        CheckConstraint("EXTRACT(DAY FROM month_accrued) = 1", name="ck_provision_origin_month"),
        CheckConstraint(
            "status IN ('DRAFT','OPEN','PARTIALLY_MATCHED','CLOSED','CANCELLED')",
            name="ck_provision_status",
        ),
        CheckConstraint(
            "currency IS NULL OR currency IN ('USD','MXN')", name="ck_provision_currency"
        ),
        finite_check(
            "ck_provision_amounts", "amount", "extra_charges", "usd_standard_cost", nonnegative=True
        ),
        CheckConstraint(
            "status IN ('DRAFT','CANCELLED') OR "
            "(amount IS NOT NULL AND extra_charges IS NOT NULL AND currency IS NOT NULL AND approved_at IS NOT NULL AND approved_by_id IS NOT NULL)",
            name="ck_provision_activation",
        ),
        CheckConstraint(
            "(fx_rate_to_usd IS NULL AND fx_rate_date IS NULL AND fx_rate_source IS NULL) OR "
            "(fx_rate_to_usd IS NOT NULL AND fx_rate_to_usd > 0 AND fx_rate_to_usd <> 'NaN'::numeric AND fx_rate_date IS NOT NULL AND fx_rate_source IS NOT NULL)",
            name="ck_provision_fx",
        ),
        CheckConstraint(
            "currency <> 'USD' OR fx_rate_to_usd IS NULL OR fx_rate_to_usd = 1",
            name="ck_provision_usd_rate",
        ),
        CheckConstraint(
            "(status IN ('CLOSED','CANCELLED') AND terminal_at IS NOT NULL AND terminal_period IS NOT NULL AND terminal_by_id IS NOT NULL AND terminal_reason IS NOT NULL) "
            "OR (status NOT IN ('CLOSED','CANCELLED') AND terminal_at IS NULL AND terminal_period IS NULL AND terminal_by_id IS NULL AND terminal_reason IS NULL)",
            name="ck_provision_terminal",
        ),
        CheckConstraint(
            "terminal_period IS NULL OR terminal_period >= month_accrued",
            name="ck_provision_terminal_month",
        ),
        CheckConstraint("row_version > 0", name="ck_provision_version"),
        Index("ix_provisions_pending", "status", "month_accrued", "shipment_id"),
    )


class Invoice(IdentityMixin, VersionedMixin, Base):
    __tablename__ = "invoices"
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    company_code: Mapped[str] = mapped_column(String(32))
    invoice_number_raw: Mapped[str] = mapped_column(String(120))
    invoice_number_normalized: Mapped[str] = mapped_column(String(120))
    normalization_version: Mapped[str] = mapped_column(String(32))
    issue_date: Mapped[date] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accounting_period: Mapped[date | None] = mapped_column(
        ForeignKey("accounting_periods.period_month", ondelete="RESTRICT")
    )
    currency: Mapped[str] = mapped_column(String(3))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), Computed("net_amount + tax_amount", persisted=True)
    )
    status: Mapped[str] = mapped_column(String(24), server_default="RECEIVED")
    uploaded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    document_location: Mapped[str | None] = mapped_column(Text)
    document_sha256: Mapped[str | None] = mapped_column(String(64))
    source_data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        UniqueConstraint(
            "company_code", "supplier_id", "invoice_number_normalized", name="uq_supplier_invoice"
        ),
        CheckConstraint("length(btrim(invoice_number_normalized)) > 0", name="ck_invoice_number"),
        CheckConstraint("currency IN ('USD','MXN')", name="ck_invoice_currency"),
        CheckConstraint(
            "status IN ('RECEIVED','UNDER_REVIEW','APPROVED','REJECTED','CANCELLED')",
            name="ck_invoice_status",
        ),
        finite_check("ck_invoice_amounts", "net_amount", "tax_amount", nonnegative=True),
        CheckConstraint("row_version > 0", name="ck_invoice_version"),
        Index("ix_invoices_supplier_received", "supplier_id", "received_at"),
        Index("ix_invoices_hash", "document_sha256"),
    )


class InvoiceLine(IdentityMixin, Base):
    __tablename__ = "invoice_lines"
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"))
    shipment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    charge_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_invoice_line"),
        CheckConstraint("line_no > 0", name="ck_invoice_line_number"),
        finite_check("ck_invoice_line_amounts", "net_amount", "tax_amount", nonnegative=True),
    )


class InvoiceLineIdentifier(IdentityMixin, Base):
    __tablename__ = "invoice_line_identifiers"
    invoice_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoice_lines.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(20))
    raw_value: Mapped[str] = mapped_column(String(200))
    normalized_value: Mapped[str] = mapped_column(String(200))
    normalization_version: Mapped[str] = mapped_column(String(32))
    __table_args__ = (
        CheckConstraint(
            "kind IN ('REFERENCE','AWB','BL','CONTAINER','PEDIMENTO','TRACKING')",
            name="ck_invoice_identifier_kind",
        ),
        CheckConstraint("length(btrim(normalized_value)) > 0", name="ck_invoice_identifier_value"),
        UniqueConstraint(
            "invoice_line_id", "kind", "normalized_value", name="uq_invoice_identifier"
        ),
        Index("ix_invoice_identifiers_lookup", "kind", "normalized_value"),
    )


class ReconciliationAllocation(IdentityMixin, Base):
    __tablename__ = "reconciliation_allocations"
    provision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provisions.id", ondelete="RESTRICT"), index=True
    )
    invoice_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoice_lines.id", ondelete="RESTRICT"), index=True
    )
    entry_type: Mapped[str] = mapped_column(String(12))
    reverses_allocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reconciliation_allocations.id", ondelete="RESTRICT"), unique=True
    )
    period_month: Mapped[date] = mapped_column(
        ForeignKey("accounting_periods.period_month", ondelete="RESTRICT"), index=True
    )
    provision_release_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    invoice_allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    provision_fx_rate_to_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    invoice_fx_rate_to_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    fx_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    expected_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        Computed("provision_release_amount * provision_fx_rate_to_usd", persisted=True),
    )
    actual_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        Computed("invoice_allocated_amount * invoice_fx_rate_to_usd", persisted=True),
    )
    variance_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        Computed(
            "invoice_allocated_amount * invoice_fx_rate_to_usd - provision_release_amount * provision_fx_rate_to_usd",
            persisted=True,
        ),
    )
    decision: Mapped[str] = mapped_column(String(8))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(String(40))
    accepted_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    __table_args__ = (
        CheckConstraint("entry_type IN ('MATCH','REVERSAL')", name="ck_allocation_entry_type"),
        CheckConstraint(
            "(entry_type = 'MATCH' AND provision_release_amount > 0 AND invoice_allocated_amount > 0 AND reverses_allocation_id IS NULL) OR "
            "(entry_type = 'REVERSAL' AND provision_release_amount < 0 AND invoice_allocated_amount < 0 AND reverses_allocation_id IS NOT NULL)",
            name="ck_allocation_sign",
        ),
        CheckConstraint(
            "reverses_allocation_id IS NULL OR reverses_allocation_id <> id",
            name="ck_allocation_reversal_target",
        ),
        CheckConstraint("decision IN ('GREEN','YELLOW','RED')", name="ck_allocation_decision"),
        CheckConstraint(
            "decision = 'GREEN' OR (decision_reason IS NOT NULL AND length(btrim(decision_reason)) > 0)",
            name="ck_allocation_reason",
        ),
        finite_check(
            "ck_allocation_amounts", "provision_release_amount", "invoice_allocated_amount"
        ),
        CheckConstraint(
            "provision_fx_rate_to_usd IS NULL OR (provision_fx_rate_to_usd > 0 AND provision_fx_rate_to_usd <> 'NaN'::numeric)",
            name="ck_allocation_provision_fx",
        ),
        CheckConstraint(
            "invoice_fx_rate_to_usd IS NULL OR (invoice_fx_rate_to_usd > 0 AND invoice_fx_rate_to_usd <> 'NaN'::numeric)",
            name="ck_allocation_invoice_fx",
        ),
    )


class ProvisionPeriod(Base):
    __tablename__ = "provision_periods"
    provision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provisions.id", ondelete="RESTRICT"), primary_key=True
    )
    period_month: Mapped[date] = mapped_column(
        ForeignKey("accounting_periods.period_month", ondelete="RESTRICT"), primary_key=True
    )
    opening_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    new_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    released_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    adjustment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    closing_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        Computed(
            "opening_amount + new_amount + adjustment_amount - released_amount", persisted=True
        ),
    )
    currency: Mapped[str] = mapped_column(String(3))
    closing_status: Mapped[str] = mapped_column(String(24))
    closing_fx_rate_to_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    fx_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rule_version: Mapped[str] = mapped_column(String(40))
    provision_row_version: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("currency IN ('USD','MXN')", name="ck_snapshot_currency"),
        CheckConstraint(
            "closing_status IN ('OPEN','PARTIALLY_MATCHED','CLOSED','CANCELLED')",
            name="ck_snapshot_status",
        ),
        CheckConstraint(
            "opening_amount >= 0 AND new_amount >= 0 AND closing_amount >= 0",
            name="ck_snapshot_balance",
        ),
        CheckConstraint(
            "closing_status NOT IN ('CLOSED','CANCELLED') OR closing_amount = 0",
            name="ck_snapshot_terminal_balance",
        ),
        finite_check(
            "ck_snapshot_amounts",
            "opening_amount",
            "new_amount",
            "released_amount",
            "adjustment_amount",
        ),
        CheckConstraint(
            "closing_fx_rate_to_usd IS NULL OR (closing_fx_rate_to_usd > 0 AND closing_fx_rate_to_usd <> 'NaN'::numeric)",
            name="ck_snapshot_fx",
        ),
        CheckConstraint("provision_row_version > 0", name="ck_snapshot_version"),
        Index("ix_provision_periods_month", "period_month"),
    )


class ReconciliationLog(IdentityMixin, Base):
    __tablename__ = "reconciliation_logs"
    shipment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT")
    )
    provision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provisions.id", ondelete="RESTRICT")
    )
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"))
    allocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reconciliation_allocations.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    service_actor: Mapped[str | None] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    severity: Mapped[str | None] = mapped_column(String(8))
    rule_version: Mapped[str | None] = mapped_column(String(40))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    before_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    __table_args__ = (
        CheckConstraint(
            "(actor_user_id IS NOT NULL AND service_actor IS NULL) OR "
            "(actor_user_id IS NULL AND service_actor IS NOT NULL AND length(btrim(service_actor)) > 0)",
            name="ck_log_actor",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('GREEN','YELLOW','RED')", name="ck_log_severity"
        ),
        Index("ix_logs_shipment_time", "shipment_id", "occurred_at"),
        Index("ix_logs_provision_time", "provision_id", "occurred_at"),
        Index("ix_logs_invoice_time", "invoice_id", "occurred_at"),
    )
