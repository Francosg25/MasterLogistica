"""Reference-level accruals, immutable invoice movements and monthly carry-forward.

Balances are derived from the ledger, never copied into a new provision each month.
Manual amounts use net values. Consolidated imports use the full USD AMOUNT as
their allocation basis, keeping original tax and currency evidence separately.
Matching requires reference, company, supplier, currency and charge to agree.
"""

import csv
import io
import re
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.api import DB, Actor, Limit, Offset, open_period, supplier_valid, version_matches
from app.auth import current_user
from app.finance_schemas import CancelInvoice, InvoiceCreate, ReconcileCommand, VersionCommand
from app.models import (
    AccountingPeriod,
    Invoice,
    InvoiceLine,
    InvoiceLineIdentifier,
    Provision,
    ReconciliationLog,
    Shipment,
    ShipmentIdentifier,
    Supplier,
    User,
)
from app.models import (
    ReconciliationAllocation as Allocation,
)
from app.references import normalize_identifier, parse_reference
from app.schemas import ProvisionCreate, ProvisionRead

router = APIRouter(prefix="/api/v1/finance", tags=["Finance"])
ZERO = Decimal("0")
RULE = "REFERENCE_NET_V1"


def finance_writer(user=Depends(current_user)):
    if user.role not in {"FINANCE", "SUPER_ADMIN"}:
        raise HTTPException(
            403, "Solo Finanzas y Administración pueden registrar movimientos financieros"
        )
    return user


FinanceWriter = Annotated[User, Depends(finance_writer)]


def finance_scope(statement, user):
    if user.role in {"FINANCE", "MANAGER", "SUPER_ADMIN"}:
        return statement
    return statement.where(Shipment.owner_id == user.id)


def finance_reader(user):
    if user.role not in {"FINANCE", "MANAGER", "SUPER_ADMIN"}:
        raise HTTPException(
            403, "La consulta de facturas requiere Finanzas, Gerencia o Administración"
        )


def month_check(value):
    if value.day != 1:
        raise HTTPException(422, "Selecciona un mes contable válido")
    return value


def financial_json(value):
    return jsonable_encoder(value, custom_encoder={Decimal: str})


def audit_event(
    session,
    request,
    user,
    action,
    *,
    shipment_id=None,
    provision_id=None,
    invoice_id=None,
    allocation_id=None,
    before=None,
    after=None,
):
    session.add(
        ReconciliationLog(
            id=uuid4(),
            actor_user_id=user.id,
            event_type=action,
            shipment_id=shipment_id,
            provision_id=provision_id,
            invoice_id=invoice_id,
            allocation_id=allocation_id,
            severity="GREEN",
            rule_version=RULE,
            evidence={"actor_name": user.display_name, "actor_email": user.email},
            before_values=financial_json(before or {}),
            after_values=financial_json(after or {}),
            request_id=UUID(request.state.request_id),
        )
    )


def commit(session):
    try:
        session.commit()
    except (IntegrityError, StaleDataError):
        session.rollback()
        raise HTTPException(
            409, "Movimiento duplicado o modificado por otro usuario; actualiza los datos"
        ) from None


def released(session, provision_id):
    return session.scalar(
        select(func.coalesce(func.sum(Allocation.provision_release_amount), 0)).where(
            Allocation.provision_id == provision_id
        )
    )


def applied(session, line_id):
    return session.scalar(
        select(func.coalesce(func.sum(Allocation.invoice_allocated_amount), 0)).where(
            Allocation.invoice_line_id == line_id
        )
    )


def provision_state(total, consumed):
    if consumed >= total:
        return "CLOSED"
    return "PARTIALLY_MATCHED" if consumed > 0 else "OPEN"


def update_provision(session, provision, user, period):
    provision.status = provision_state(provision.total_amount, released(session, provision.id))
    if provision.status == "CLOSED":
        provision.terminal_at = datetime.now(UTC)
        provision.terminal_period = period
        provision.terminal_by_id = user.id
        provision.terminal_reason = "Liquidada por conciliación de facturas"
    else:
        provision.terminal_at = provision.terminal_period = None
        provision.terminal_by_id = provision.terminal_reason = None


def lock_shipments(session, ids):
    # Same ordering for all writers; serializes approvals, matching and reversals per reference.
    return session.scalars(
        select(Shipment).where(Shipment.id.in_(ids)).order_by(Shipment.id).with_for_update()
    ).all()


def invoice_snapshot(session, row):
    lines = session.execute(
        select(InvoiceLine, Shipment.reference_raw)
        .outerjoin(Shipment, Shipment.id == InvoiceLine.shipment_id)
        .where(InvoiceLine.invoice_id == row.id)
        .order_by(InvoiceLine.line_no)
    ).all()
    supplier = session.get(Supplier, row.supplier_id)
    items = []
    for line, reference in lines:
        consumed = applied(session, line.id)
        items.append(
            dict(
                id=line.id,
                reference=reference,
                shipment_id=line.shipment_id,
                charge_code=line.charge_code,
                net_amount=line.net_amount,
                tax_amount=line.tax_amount,
                applied_amount=consumed,
                pending_amount=ZERO if row.status == "CANCELLED" else line.net_amount - consumed,
                description=line.description,
            )
        )
    return financial_json(
        dict(
            id=row.id,
            row_version=row.row_version,
            invoice_number=row.invoice_number_raw,
            supplier_id=row.supplier_id,
            supplier_name=supplier.legal_name,
            company_code=row.company_code,
            currency=row.currency,
            issue_date=row.issue_date,
            accounting_period=row.accounting_period,
            status=row.status,
            net_amount=row.net_amount,
            tax_amount=row.tax_amount,
            gross_amount=row.gross_amount,
            amount_basis=(row.source_data or {}).get("amount_basis", "NET"),
            source_data=row.source_data or {},
            applied_amount=sum((x["applied_amount"] for x in items), ZERO),
            pending_amount=sum((x["pending_amount"] for x in items), ZERO),
            lines=items,
        )
    )


def match_invoice(session, row, period, user, request):
    if row.status in {"CANCELLED", "REJECTED"}:
        raise HTTPException(409, "No se puede conciliar una factura cancelada o rechazada")
    if not row.accounting_period or period < row.accounting_period:
        raise HTTPException(422, "La conciliación no puede ser anterior al registro de la factura")
    lines = session.scalars(
        select(InvoiceLine)
        .where(InvoiceLine.invoice_id == row.id)
        .order_by(InvoiceLine.shipment_id, InvoiceLine.line_no)
    ).all()
    lock_shipments(session, [x.shipment_id for x in lines if x.shipment_id])
    last_period = session.scalar(
        select(func.max(Allocation.period_month))
        .join(InvoiceLine)
        .where(InvoiceLine.invoice_id == row.id)
    )
    if last_period and period < last_period:
        raise HTTPException(409, "No se puede conciliar antes del último movimiento de la factura")
    count = 0
    for line in lines:
        remaining = line.net_amount - applied(session, line.id)
        if remaining <= 0 or not line.shipment_id:
            continue
        provisions = session.scalars(
            select(Provision)
            .where(
                Provision.shipment_id == line.shipment_id,
                Provision.supplier_id == row.supplier_id,
                Provision.currency == row.currency,
                Provision.charge_code == line.charge_code,
                Provision.month_accrued <= period,
                Provision.status.in_(["OPEN", "PARTIALLY_MATCHED"]),
            )
            .order_by(Provision.month_accrued, Provision.id)
            .with_for_update()
        ).all()
        for provision in provisions:
            newest = session.scalar(
                select(func.max(Allocation.period_month)).where(
                    Allocation.provision_id == provision.id
                )
            )
            if newest and period < newest:
                raise HTTPException(
                    409, "La referencia tiene movimientos posteriores; usa ese mes o uno posterior"
                )
            balance = provision.total_amount - released(session, provision.id)
            amount = min(balance, remaining)
            if amount <= 0:
                continue
            entry = Allocation(
                id=uuid4(),
                provision_id=provision.id,
                invoice_line_id=line.id,
                entry_type="MATCH",
                period_month=period,
                provision_release_amount=amount,
                invoice_allocated_amount=amount,
                decision="GREEN",
                rule_version="REFERENCE_USD_AMOUNT_V1"
                if (row.source_data or {}).get("amount_basis") == "USD_AMOUNT"
                else RULE,
                accepted_by_id=user.id,
                idempotency_key=str(uuid4()),
            )
            session.add(entry)
            session.flush()
            before = {"status": provision.status, "balance": balance}
            update_provision(session, provision, user, period)
            audit_event(
                session,
                request,
                user,
                "INVOICE_MATCHED",
                shipment_id=line.shipment_id,
                provision_id=provision.id,
                invoice_id=row.id,
                allocation_id=entry.id,
                before=before,
                after={
                    "status": provision.status,
                    "balance": balance - amount,
                    "amount": amount,
                    "currency": row.currency,
                    "invoice_number": row.invoice_number_raw,
                    "period_month": period,
                },
            )
            remaining -= amount
            count += 1
            if remaining == 0:
                break
    pending = sum((line.net_amount - applied(session, line.id) for line in lines), ZERO)
    row.status = "APPROVED" if pending == 0 else "UNDER_REVIEW"
    # Version also advances when matching additional lines while status stays UNDER_REVIEW.
    if count:
        row.row_version += 1
    session.flush()
    return count


@router.get("/owners")
def owners(session: DB, user: Actor):
    statement = select(User).where(
        or_(User.analyst_code.is_not(None), User.id.in_(select(Shipment.owner_id)))
    )
    if user.role == "OPERATOR":
        statement = statement.where(User.id == user.id)
    return [
        dict(id=x.id, display_name=x.display_name)
        for x in session.scalars(statement.order_by(User.display_name))
    ]


@router.get("/references")
def references(session: DB, user: Actor, q: Annotated[str, Query(max_length=160)] = ""):
    statement = finance_scope(
        select(Shipment).where(Shipment.status != "CANCELLED", Shipment.reference_raw.is_not(None)),
        user,
    )
    if q.strip():
        value = q.strip()
        aliases = select(ShipmentIdentifier.shipment_id).where(
            ShipmentIdentifier.raw_value.icontains(value, autoescape=True)
        )
        statement = statement.where(
            or_(Shipment.reference_raw.icontains(value, autoescape=True), Shipment.id.in_(aliases))
        )
    statement = statement.outerjoin(User, User.id == Shipment.owner_id)
    return [
        dict(
            id=x.id,
            reference=x.reference_raw,
            company_code=x.company_code,
            owner_id=x.owner_id,
            owner_name=name,
            business_unit=x.business_unit,
        )
        for x, name in session.execute(
            statement.with_only_columns(Shipment, User.display_name)
            .order_by(Shipment.reference_raw)
            .limit(30)
        )
    ]


@router.post("/periods", status_code=201)
def create_period(period_month: date, session: DB, user: FinanceWriter, request: Request):
    month_check(period_month)
    row = session.get(AccountingPeriod, period_month)
    if row is None:
        row = AccountingPeriod(period_month=period_month, status="OPEN")
        session.add(row)
        audit_event(session, request, user, "PERIOD_CREATED", after={"period_month": period_month})
        commit(session)
    elif row.status != "OPEN":
        raise HTTPException(409, "Ese periodo ya está cerrado")
    return dict(period_month=row.period_month, status=row.status)


@router.post("/provisions", response_model=ProvisionRead, status_code=201)
def create_provision(data: ProvisionCreate, session: DB, user: FinanceWriter, request: Request):
    open_period(session, data.month_accrued)
    shipments = lock_shipments(session, [data.shipment_id])
    if not shipments:
        raise HTTPException(404, "Referencia no encontrada")
    if shipments[0].status == "CANCELLED":
        raise HTTPException(409, "La referencia está cancelada")
    supplier_valid(session, data.supplier_id)
    if (
        data.amount is None
        or data.extra_charges is None
        or not data.currency
        or data.amount + data.extra_charges <= 0
    ):
        raise HTTPException(422, "Captura moneda e importe neto positivo")
    row = Provision(id=uuid4(), **data.model_dump(), status="DRAFT")
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "Ya existe esa línea de provisión para la referencia y proveedor"
        ) from None
    audit_event(
        session,
        request,
        user,
        "PROVISION_DRAFT_CREATED",
        shipment_id=row.shipment_id,
        provision_id=row.id,
        after=data.model_dump(mode="json"),
    )
    commit(session)
    session.refresh(row)
    return row


@router.post("/provisions/{provision_id}/approve", response_model=ProvisionRead)
def approve(
    provision_id: UUID, data: VersionCommand, session: DB, user: FinanceWriter, request: Request
):
    row = session.get(Provision, provision_id)
    if row is None:
        raise HTTPException(404, "Provisión no encontrada")
    open_period(session, row.month_accrued)
    lock_shipments(session, [row.shipment_id])
    session.refresh(row, with_for_update=True)
    version_matches(row, data.expected_version)
    if (
        row.status != "DRAFT"
        or row.total_amount is None
        or row.total_amount <= 0
        or not row.currency
    ):
        raise HTTPException(409, "Solo se aprueban borradores completos con importe positivo")
    row.status, row.approved_at, row.approved_by_id = "OPEN", datetime.now(UTC), user.id
    audit_event(
        session,
        request,
        user,
        "PROVISION_APPROVED",
        shipment_id=row.shipment_id,
        provision_id=row.id,
        before={"status": "DRAFT"},
        after={
            "status": "OPEN",
            "total_amount": row.total_amount,
            "currency": row.currency,
            "month_accrued": row.month_accrued,
        },
    )
    commit(session)
    session.refresh(row)
    return row


@router.post("/invoices", status_code=201)
def create_invoice(data: InvoiceCreate, session: DB, user: FinanceWriter, request: Request):
    return register_invoice(data, session, user, request)


def register_invoice(data, session, user, request, *, source_data=None, persist=True):
    open_period(session, data.accounting_period)
    supplier_valid(session, data.supplier_id)
    try:
        normalized = normalize_identifier(data.invoice_number)
    except ValueError:
        raise HTTPException(422, "El folio solo admite letras, números y separadores") from None
    if session.scalar(
        select(Invoice.id).where(
            Invoice.company_code == data.company_code,
            Invoice.supplier_id == data.supplier_id,
            Invoice.invoice_number_normalized == normalized,
        )
    ):
        raise HTTPException(409, "Esa factura ya está registrada para la empresa y proveedor")
    resolved = []
    for item in data.lines:
        try:
            value = parse_reference(item.reference).normalized
        except ValueError:
            value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", item.reference)).upper()
        ids = select(ShipmentIdentifier.shipment_id).where(
            ShipmentIdentifier.kind == "REFERENCE", ShipmentIdentifier.normalized_value == value
        )
        candidates = session.scalars(
            select(Shipment).where(
                Shipment.company_code == data.company_code,
                or_(Shipment.reference_normalized == value, Shipment.id.in_(ids)),
            )
        ).all()
        if len(candidates) != 1:
            raise HTTPException(
                422, f"La referencia {item.reference} no identifica un embarque de esa empresa"
            )
        resolved.append((item, candidates[0]))
    row = Invoice(
        id=uuid4(),
        supplier_id=data.supplier_id,
        company_code=data.company_code,
        invoice_number_raw=data.invoice_number.strip(),
        invoice_number_normalized=normalized,
        normalization_version="IDENTIFIER_V1",
        issue_date=data.issue_date,
        accounting_period=data.accounting_period,
        currency=data.currency,
        net_amount=sum(x.net_amount for x in data.lines),
        tax_amount=sum(x.tax_amount for x in data.lines),
        status="RECEIVED",
        uploaded_by_id=user.id,
        source_data=source_data or {},
        document_sha256=(source_data or {}).get("sha256"),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "La factura ya fue registrada; actualiza la lista") from None
    for index, (item, shipment) in enumerate(resolved, 1):
        line = InvoiceLine(
            id=uuid4(),
            invoice_id=row.id,
            shipment_id=shipment.id,
            line_no=index,
            charge_code=item.charge_code,
            description=item.description,
            net_amount=item.net_amount,
            tax_amount=item.tax_amount,
        )
        session.add(line)
        session.flush()
        session.add(
            InvoiceLineIdentifier(
                invoice_line_id=line.id,
                kind="REFERENCE",
                raw_value=item.reference,
                normalized_value=normalize_identifier(item.reference),
                normalization_version="IDENTIFIER_V1",
            )
        )
        audit_event(
            session,
            request,
            user,
            "INVOICE_REGISTERED",
            shipment_id=shipment.id,
            invoice_id=row.id,
            after={
                "invoice_number": row.invoice_number_raw,
                "line_no": index,
                "reference": shipment.reference_raw,
                "net_amount": item.net_amount,
                "tax_amount": item.tax_amount,
                "currency": row.currency,
                "accounting_period": row.accounting_period,
                "amount_basis": (source_data or {}).get("amount_basis", "NET"),
                "source_file": (source_data or {}).get("filename"),
                "source_rows": (source_data or {}).get("row_numbers"),
            },
        )
    session.flush()
    match_invoice(session, row, data.accounting_period, user, request)
    if persist:
        commit(session)
        session.refresh(row)
        return invoice_snapshot(session, row)
    return row


@router.get("/invoices")
def invoices(
    session: DB,
    user: Actor,
    limit: Limit = 20,
    offset: Offset = 0,
    q: str = "",
    status: str | None = None,
):
    finance_reader(user)
    statement = select(Invoice)
    if q.strip():
        refs = (
            select(InvoiceLine.invoice_id)
            .join(Shipment)
            .where(Shipment.reference_raw.icontains(q.strip(), autoescape=True))
        )
        statement = statement.where(
            or_(
                Invoice.invoice_number_raw.icontains(q.strip(), autoescape=True),
                Invoice.id.in_(refs),
            )
        )
    if status:
        statement = statement.where(Invoice.status == status)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = session.scalars(
        statement.order_by(Invoice.created_at.desc(), Invoice.id).limit(limit).offset(offset)
    )
    return dict(
        items=[invoice_snapshot(session, x) for x in rows], total=total, limit=limit, offset=offset
    )


@router.post("/invoices/{invoice_id}/reconcile")
def reconcile(
    invoice_id: UUID, data: ReconcileCommand, session: DB, user: FinanceWriter, request: Request
):
    open_period(session, data.period_month)
    row = session.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Factura no encontrada")
    version_matches(row, data.expected_version)
    match_invoice(session, row, data.period_month, user, request)
    commit(session)
    return invoice_snapshot(session, row)


@router.post("/invoices/{invoice_id}/cancel")
def cancel_invoice(
    invoice_id: UUID, data: CancelInvoice, session: DB, user: FinanceWriter, request: Request
):
    open_period(session, data.period_month)
    row = session.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Factura no encontrada")
    version_matches(row, data.expected_version)
    if row.status == "CANCELLED":
        raise HTTPException(409, "La factura ya está cancelada")
    if data.period_month < row.accounting_period:
        raise HTTPException(422, "La cancelación no puede ser anterior al registro")
    lines = session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == row.id)).all()
    lock_shipments(session, [line.shipment_id for line in lines if line.shipment_id])
    entries = session.scalars(
        select(Allocation).where(
            Allocation.invoice_line_id.in_([x.id for x in lines]), Allocation.entry_type == "MATCH"
        )
    ).all()
    touched = set()
    for entry in entries:
        newest = session.scalar(
            select(func.max(Allocation.period_month)).where(
                Allocation.provision_id == entry.provision_id
            )
        )
        if data.period_month < newest:
            raise HTTPException(
                409, "La reversión debe registrarse en el mes del último movimiento o uno posterior"
            )
        reverse = Allocation(
            id=uuid4(),
            provision_id=entry.provision_id,
            invoice_line_id=entry.invoice_line_id,
            entry_type="REVERSAL",
            reverses_allocation_id=entry.id,
            period_month=data.period_month,
            provision_release_amount=-entry.provision_release_amount,
            invoice_allocated_amount=-entry.invoice_allocated_amount,
            decision="YELLOW",
            decision_reason=data.reason,
            rule_version=entry.rule_version,
            accepted_by_id=user.id,
            idempotency_key="cancel:" + str(entry.id),
        )
        session.add(reverse)
        touched.add(entry.provision_id)
    session.flush()
    for provision_id in touched:
        provision = session.get(Provision, provision_id)
        before = {
            "status": provision.status,
            "balance": provision.total_amount
            - released(session, provision.id)
            - sum(x.provision_release_amount for x in entries if x.provision_id == provision.id),
        }
        update_provision(session, provision, user, data.period_month)
        audit_event(
            session,
            request,
            user,
            "INVOICE_REVERSED",
            shipment_id=provision.shipment_id,
            provision_id=provision.id,
            invoice_id=row.id,
            before=before,
            after={
                "status": provision.status,
                "balance": provision.total_amount - released(session, provision.id),
                "reason": data.reason,
                "period_month": data.period_month,
                "invoice_number": row.invoice_number_raw,
            },
        )
    for line in lines:
        audit_event(
            session,
            request,
            user,
            "INVOICE_CANCELLED",
            invoice_id=row.id,
            shipment_id=line.shipment_id,
            before={"status": row.status},
            after={
                "status": "CANCELLED",
                "reason": data.reason,
                "period_month": data.period_month,
                "invoice_number": row.invoice_number_raw,
            },
        )
    row.status = "CANCELLED"
    commit(session)
    return invoice_snapshot(session, row)


def balance_rows(session, user, month, q="", owner_id=None, operation_code=None):
    month_check(month)
    sums = (
        select(
            Allocation.provision_id,
            func.sum(
                case(
                    (Allocation.period_month < month, Allocation.provision_release_amount), else_=0
                )
            ).label("prior"),
            func.sum(
                case(
                    (Allocation.period_month == month, Allocation.provision_release_amount), else_=0
                )
            ).label("movement"),
        )
        .where(Allocation.period_month <= month)
        .group_by(Allocation.provision_id)
        .subquery()
    )
    statement = finance_scope(
        select(
            Provision,
            Shipment,
            Supplier.legal_name,
            User.display_name,
            func.coalesce(sums.c.prior, 0),
            func.coalesce(sums.c.movement, 0),
        )
        .join(Shipment, Shipment.id == Provision.shipment_id)
        .join(Supplier, Supplier.id == Provision.supplier_id)
        .join(User, User.id == Shipment.owner_id)
        .outerjoin(sums, sums.c.provision_id == Provision.id)
        .where(Provision.month_accrued <= month),
        user,
    )
    if q.strip():
        statement = statement.where(Shipment.reference_raw.icontains(q.strip(), autoescape=True))
    if owner_id:
        statement = statement.where(Shipment.owner_id == owner_id)
    if operation_code:
        statement = statement.where(Shipment.operation_code == operation_code)
    result = []
    for p, s, supplier, owner, prior, movement in session.execute(
        statement.order_by(Provision.month_accrued, Shipment.reference_raw, Provision.id)
    ):
        total = p.total_amount or ZERO
        draft = p.status == "DRAFT"
        # Legacy cancellations are excluded from live balances starting in their terminal period.
        cancelled = p.status == "CANCELLED" and p.terminal_period and p.terminal_period <= month
        opening = total - prior if p.month_accrued < month and not draft else ZERO
        new = total if p.month_accrued == month and not draft else ZERO
        adjustment = -(opening + new - movement) if cancelled else ZERO
        closing = opening + new + adjustment - movement
        result.append(
            dict(
                id=p.id,
                row_version=p.row_version,
                shipment_id=s.id,
                reference=s.reference_raw,
                owner_name=owner,
                owner_id=s.owner_id,
                operation_code=s.operation_code,
                company_code=s.company_code,
                supplier_name=supplier,
                supplier_id=p.supplier_id,
                charge_code=p.charge_code,
                line_no=p.line_no,
                currency=p.currency,
                month_accrued=p.month_accrued,
                provision_date=p.provision_date,
                period_month=month,
                total_amount=total,
                opening_amount=opening,
                new_amount=new,
                released_amount=movement,
                adjustment_amount=adjustment,
                closing_amount=closing,
                status="DRAFT"
                if draft
                else "CANCELLED"
                if cancelled
                else provision_state(total, prior + movement),
                current_status=p.status,
            )
        )
    return result


def totals(rows):
    values = {}
    for row in rows:
        if row["status"] == "DRAFT" or not row["currency"]:
            continue
        group = values.setdefault(
            row["currency"],
            {
                key: ZERO
                for key in (
                    "opening_amount",
                    "new_amount",
                    "released_amount",
                    "adjustment_amount",
                    "closing_amount",
                )
            },
        )
        for key in group:
            group[key] += row[key]
    return [dict(currency=currency, **amounts) for currency, amounts in sorted(values.items())]


@router.get("/balances")
def balances(
    session: DB,
    user: Actor,
    month: date,
    q: str = "",
    owner_id: UUID | None = None,
    operation_code: str | None = None,
    status: str | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
):
    rows = balance_rows(session, user, month, q, owner_id, operation_code)
    if status:
        rows = [x for x in rows if x["status"] == status]
    return financial_json(
        dict(
            items=rows[offset : offset + limit],
            total=len(rows),
            limit=limit,
            offset=offset,
            totals=totals(rows),
        )
    )


def report_data(session, user, month, q="", owner_id=None, operation_code=None):
    balances = balance_rows(session, user, month, q, owner_id, operation_code)
    statement = finance_scope(
        select(
            Allocation,
            Invoice.invoice_number_raw,
            Invoice.currency,
            Invoice.source_data,
            Shipment.reference_raw,
            Supplier.legal_name,
            Provision.month_accrued,
            User.display_name,
        )
        .join(Provision, Provision.id == Allocation.provision_id)
        .join(Shipment, Shipment.id == Provision.shipment_id)
        .join(InvoiceLine, InvoiceLine.id == Allocation.invoice_line_id)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Supplier, Supplier.id == Invoice.supplier_id)
        .join(User, User.id == Allocation.accepted_by_id)
        .where(Allocation.period_month == month),
        user,
    )
    pending_stmt = finance_scope(
        select(InvoiceLine, Invoice, Shipment.reference_raw, Supplier.legal_name)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Shipment, Shipment.id == InvoiceLine.shipment_id)
        .join(Supplier, Supplier.id == Invoice.supplier_id)
        .where(Invoice.accounting_period <= month),
        user,
    )
    for column, value in ((Shipment.owner_id, owner_id), (Shipment.operation_code, operation_code)):
        if value:
            statement, pending_stmt = (
                statement.where(column == value),
                pending_stmt.where(column == value),
            )
    if q.strip():
        condition = Shipment.reference_raw.icontains(q.strip(), autoescape=True)
        statement, pending_stmt = statement.where(condition), pending_stmt.where(condition)
    movements = [
        dict(
            id=a.id,
            reference=ref,
            invoice_number=number,
            supplier_name=supplier,
            currency=currency,
            month_accrued=origin,
            period_month=a.period_month,
            entry_type=a.entry_type,
            amount=a.invoice_allocated_amount,
            actor_name=actor,
            occurred_at=a.accepted_at,
            amount_basis=(source or {}).get("amount_basis", "NET"),
        )
        for a, number, currency, source, ref, supplier, origin, actor in session.execute(
            statement.order_by(Allocation.accepted_at, Allocation.id)
        )
    ]
    pending = []
    # Cancellation takes effect in its accounting month, not retroactively in earlier reports.
    cancellations = dict(
        session.execute(
            select(
                ReconciliationLog.invoice_id,
                func.min(ReconciliationLog.after_values["period_month"].as_string()),
            )
            .where(ReconciliationLog.event_type == "INVOICE_CANCELLED")
            .group_by(ReconciliationLog.invoice_id)
        ).all()
    )
    sums = dict(
        session.execute(
            select(Allocation.invoice_line_id, func.sum(Allocation.invoice_allocated_amount))
            .where(Allocation.period_month <= month)
            .group_by(Allocation.invoice_line_id)
        ).all()
    )
    for line, inv, ref, supplier in session.execute(
        pending_stmt.order_by(Invoice.accounting_period, Invoice.id, InvoiceLine.line_no)
    ):
        if cancellations.get(inv.id, "9999-12-01") <= month.isoformat():
            continue
        remaining = line.net_amount - sums.get(line.id, ZERO)
        if remaining > 0:
            pending.append(
                dict(
                    reference=ref,
                    invoice_number=inv.invoice_number_raw,
                    supplier_name=supplier,
                    period_month=inv.accounting_period,
                    currency=inv.currency,
                    amount_basis=(inv.source_data or {}).get("amount_basis", "NET"),
                    amount=remaining,
                    charge_code=line.charge_code,
                    entry_type="UNPROVISIONED",
                )
            )
    return dict(
        month=month,
        balances=balances,
        totals=totals(balances),
        movements=movements,
        pending_invoices=pending,
    )


@router.get("/report")
def report(
    session: DB,
    user: Actor,
    month: date,
    q: str = "",
    owner_id: UUID | None = None,
    operation_code: str | None = None,
):
    return financial_json(report_data(session, user, month, q, owner_id, operation_code))


def safe_csv(value):
    if value is None:
        return ""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return str(value)


@router.get("/report.csv")
def report_csv(
    session: DB,
    user: Actor,
    month: date,
    q: str = "",
    owner_id: UUID | None = None,
    operation_code: str | None = None,
):
    data = report_data(session, user, month, q, owner_id, operation_code)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Tipo",
            "Mes reporte",
            "Referencia",
            "Proveedor",
            "Concepto",
            "Moneda",
            "Mes origen/registro",
            "Factura",
            "Provision original",
            "Saldo inicial",
            "Alta del mes",
            "Provision aplicada del mes",
            "Ajuste",
            "Saldo final",
            "Movimiento factura",
            "Estado",
            "Usuario",
            "Base de conciliacion",
            "Fecha provision",
        ]
    )
    for b in data["balances"]:
        writer.writerow(
            [
                safe_csv(x)
                for x in [
                    "SALDO",
                    month,
                    b["reference"],
                    b["supplier_name"],
                    b["charge_code"],
                    b["currency"],
                    b["month_accrued"],
                    "",
                    b["total_amount"],
                    b["opening_amount"],
                    b["new_amount"],
                    b["released_amount"],
                    b["adjustment_amount"],
                    b["closing_amount"],
                    "",
                    b["status"],
                    b["owner_name"],
                    "",
                    b["provision_date"] or "",
                ]
            ]
        )
    for m in data["movements"] + data["pending_invoices"]:
        writer.writerow(
            [
                safe_csv(x)
                for x in [
                    m["entry_type"],
                    month,
                    m["reference"],
                    m["supplier_name"],
                    m.get("charge_code", ""),
                    m["currency"],
                    m.get("month_accrued", m["period_month"]),
                    m["invoice_number"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    m["amount"],
                    "",
                    m.get("actor_name", ""),
                    m.get("amount_basis", "NET"),
                    "",
                ]
            ]
        )
    return Response(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="conciliacion-{month:%Y-%m}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/history")
def history(
    session: DB,
    user: Actor,
    limit: Limit = 20,
    offset: Offset = 0,
    q: str = "",
    actor: str = "",
    action: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    owner_id: UUID | None = None,
    operation_code: str | None = None,
    shipment_id: UUID | None = None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "La fecha inicial es posterior a la final")
    statement = (
        select(ReconciliationLog, User.display_name, User.email, Shipment.reference_raw)
        .outerjoin(User, User.id == ReconciliationLog.actor_user_id)
        .outerjoin(Shipment, Shipment.id == ReconciliationLog.shipment_id)
    )
    if user.role not in {"SUPER_ADMIN", "MANAGER", "FINANCE"}:
        statement = statement.where(Shipment.owner_id == user.id)
    elif user.role != "SUPER_ADMIN":
        statement = statement.where(ReconciliationLog.shipment_id.is_not(None))
    for column, value in (
        (Shipment.id, shipment_id),
        (Shipment.owner_id, owner_id),
        (Shipment.operation_code, operation_code),
        (ReconciliationLog.event_type, action),
    ):
        if value:
            statement = statement.where(column == value)
    if q.strip():
        statement = statement.where(Shipment.reference_raw.icontains(q.strip(), autoescape=True))
    if actor.strip():
        statement = statement.where(
            or_(
                User.display_name.icontains(actor.strip(), autoescape=True),
                ReconciliationLog.evidence["actor_name"].astext.icontains(
                    actor.strip(), autoescape=True
                ),
            )
        )
    # UTC day boundaries are explicit; the UI labels this date filter UTC.
    if date_from:
        statement = statement.where(
            ReconciliationLog.occurred_at >= datetime.combine(date_from, time.min, UTC)
        )
    if date_to:
        statement = statement.where(
            ReconciliationLog.occurred_at
            < datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        )
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = session.execute(
        statement.order_by(ReconciliationLog.occurred_at.desc(), ReconciliationLog.id)
        .limit(limit)
        .offset(offset)
    )
    items = []
    ignored = {"id", "row_version", "created_at", "updated_at"}
    for log, name, email, ref in rows:
        before, after = log.before_values or {}, log.after_values or {}
        changes = [
            dict(field=key, before=before.get(key), after=after.get(key))
            for key in sorted((before.keys() | after.keys()) - ignored)
            if before.get(key) != after.get(key)
        ]
        items.append(
            dict(
                id=log.id,
                reference=ref,
                event_type=log.event_type,
                occurred_at=log.occurred_at,
                actor_name=(log.evidence or {}).get("actor_name") or name or log.service_actor,
                actor_email=(log.evidence or {}).get("actor_email") or email,
                shipment_id=log.shipment_id,
                provision_id=log.provision_id,
                invoice_id=log.invoice_id,
                changes=changes,
            )
        )
    return dict(items=items, total=total, limit=limit, offset=offset)


@router.get("/references/{shipment_id}/activity")
def reference_activity(shipment_id: UUID, session: DB, user: Actor):
    shipment = session.scalar(
        finance_scope(select(Shipment).where(Shipment.id == shipment_id), user)
    )
    if not shipment:
        raise HTTPException(404, "Referencia no disponible para tu usuario")
    provisions = session.execute(
        select(Provision, Supplier.legal_name)
        .join(Supplier)
        .where(Provision.shipment_id == shipment_id)
        .order_by(Provision.month_accrued, Provision.id)
    ).all()
    lines = session.execute(
        select(InvoiceLine, Invoice, Supplier.legal_name)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Supplier, Supplier.id == Invoice.supplier_id)
        .where(InvoiceLine.shipment_id == shipment_id)
        .order_by(Invoice.accounting_period, Invoice.created_at)
    ).all()
    return financial_json(
        dict(
            reference=shipment.reference_raw,
            provisions=[
                dict(
                    id=p.id,
                    supplier=supplier,
                    concept=p.charge_code,
                    month=p.month_accrued,
                    provision_date=p.provision_date,
                    currency=p.currency,
                    total=p.total_amount,
                    balance=p.total_amount - released(session, p.id)
                    if p.total_amount is not None and p.status not in {"DRAFT", "CANCELLED"}
                    else None,
                    status=p.status,
                )
                for p, supplier in provisions
            ],
            invoices=[
                dict(
                    id=line.id,
                    invoice_number=invoice.invoice_number_raw,
                    supplier=supplier,
                    concept=line.charge_code,
                    month=invoice.accounting_period,
                    currency=invoice.currency,
                    amount=line.net_amount,
                    applied=applied(session, line.id),
                    status=invoice.status,
                    amount_basis=(invoice.source_data or {}).get("amount_basis", "NET"),
                )
                for line, invoice, supplier in lines
            ],
            history=history(session, user, limit=100, shipment_id=shipment_id),
        )
    )
