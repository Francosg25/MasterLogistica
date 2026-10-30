"""Reference families are navigation groups; each movement keeps its own financial ledger."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select

from app.api import DB, Actor, owned, shipment_for
from app.finance import balance_rows, finance_scope, financial_json, totals
from app.models import Invoice, InvoiceLine, Shipment, ShipmentIdentifier, User
from app.references import normalize_reference, parse_reference
from app.schemas import ShipmentRead

router = APIRouter(prefix="/api/v1", tags=["Reference families"])


def family_spellings(value):
    """Recognize legacy numeric spellings without changing any financial matching key."""
    try:
        parsed = parse_reference(value or "")
    except ValueError:
        return {value} if value else set()
    if parsed.movement_number:
        return set()
    if not parsed.department_code:
        return {parsed.family_base}
    return {
        f"{parsed.process_code}{parsed.analyst_code}-{parsed.sequence:0{width}d}{parsed.operation_code}{parsed.year % 100:02d}-{parsed.business_unit}-{parsed.department_code}"
        for width in range(1, 11)
    }


def prepare_movement(session, user, data):
    parent = shipment_for(session, user, data.parent_shipment_id)
    # PostgreSQL locks the root; local SQLite already serializes the whole transaction.
    session.execute(select(Shipment.id).where(Shipment.id == parent.id).with_for_update()).all()
    if parent.parent_shipment_id:
        raise HTTPException(422, "Selecciona la referencia madre para añadir un movimiento")
    if parent.status == "CANCELLED":
        raise HTTPException(422, "La referencia madre está cancelada")
    try:
        parsed = parse_reference(parent.reference_raw or "")
    except ValueError:
        raise HTTPException(
            422, "Completa la nomenclatura de la referencia madre antes de añadir movimientos"
        ) from None
    if parsed.movement_number:
        raise HTTPException(422, "Selecciona la referencia madre sin distintivos")
    if data.reference_raw is not None:
        raise HTTPException(422, "El número del movimiento se asigna automáticamente")
    if any(
        getattr(data, field) != getattr(parent, field)
        for field in (
            "company_code",
            "process_code",
            "operation_code",
            "reference_year",
            "business_unit",
            "department_code",
        )
    ):
        raise HTTPException(
            422, "El movimiento debe conservar la clasificación de su referencia madre"
        )
    number = session.scalar(
        select(func.coalesce(func.max(Shipment.movement_number), 0)).where(
            Shipment.parent_shipment_id == parent.id
        )
    )
    # Reserve historical numeric references and aliases too, without merging their accounts.
    root_aliases = list(
        session.scalars(
            select(ShipmentIdentifier.normalized_value).where(
                ShipmentIdentifier.shipment_id == parent.id, ShipmentIdentifier.kind == "REFERENCE"
            )
        )
    )
    bases = set().union(
        *(family_spellings(value) for value in [parent.reference_normalized, *root_aliases])
    )
    conditions = [
        Shipment.reference_normalized.startswith(base + ".", autoescape=True) for base in bases
    ]
    values = (
        list(session.scalars(select(Shipment.reference_normalized).where(or_(*conditions))))
        if conditions
        else []
    )
    aliases = [
        ShipmentIdentifier.normalized_value.startswith(base + ".", autoescape=True)
        for base in bases
    ]
    if aliases:
        values += list(
            session.scalars(
                select(ShipmentIdentifier.normalized_value).where(
                    ShipmentIdentifier.kind == "REFERENCE", or_(*aliases)
                )
            )
        )
    for value in values:
        try:
            candidate = parse_reference(value)
            if candidate.family_base in bases:
                number = max(number, candidate.movement_number or 0)
        except ValueError:
            continue
    if number >= 999999999:
        raise HTTPException(409, "Se agotó el consecutivo de movimientos de esta referencia")
    return parent, f"{parsed.family_base}.{number + 1}", number + 1


@router.get("/shipments/{shipment_id}/family")
def family(shipment_id: UUID, session: DB, user: Actor):
    current = shipment_for(session, user, shipment_id)
    root = current
    if current.parent_shipment_id:
        # Never disclose a root outside the caller's authorized scope.
        root = (
            session.scalar(
                owned(select(Shipment).where(Shipment.id == current.parent_shipment_id), user)
            )
            or current
        )
    else:
        try:
            parsed = parse_reference(current.reference_raw or "")
            if parsed.movement_number:
                aliases = select(ShipmentIdentifier.shipment_id).where(
                    ShipmentIdentifier.kind == "REFERENCE",
                    ShipmentIdentifier.normalized_value.in_(
                        {parsed.family_base, normalize_reference(parsed.family_base)}
                    ),
                )
                matches = session.scalars(
                    owned(
                        select(Shipment).where(
                            or_(
                                Shipment.reference_normalized.in_(
                                    {parsed.family_base, normalize_reference(parsed.family_base)}
                                ),
                                Shipment.id.in_(aliases),
                            ),
                            Shipment.company_code == current.company_code,
                        ),
                        user,
                    ).limit(2)
                ).all()
                if len(matches) == 1:
                    root = matches[0]
        except ValueError:
            pass
    bases = {root.reference_normalized}
    bases.update(
        session.scalars(
            select(ShipmentIdentifier.normalized_value).where(
                ShipmentIdentifier.shipment_id == root.id, ShipmentIdentifier.kind == "REFERENCE"
            )
        )
    )
    bases = set().union(*(family_spellings(base) for base in bases))
    candidates = session.scalars(
        owned(
            select(Shipment).where(
                Shipment.company_code == root.company_code,
                or_(
                    Shipment.id == root.id,
                    Shipment.id == current.id,
                    Shipment.parent_shipment_id == root.id,
                    *[
                        Shipment.reference_normalized.startswith(base + ".", autoescape=True)
                        for base in bases
                        if base
                    ],
                ),
            ),
            user,
        )
    ).all()
    members = []
    names = dict(session.execute(select(User.id, User.display_name)).all())
    for row in candidates:
        number = row.movement_number
        if row.id == root.id and number is None:
            try:
                number = parse_reference(row.reference_raw or "").movement_number
            except ValueError:
                pass
        if row.id != root.id and row.parent_shipment_id != root.id:
            try:
                parsed = parse_reference(row.reference_raw or "")
                if parsed.family_base not in bases or not parsed.movement_number or parsed.suffix:
                    continue
                number = parsed.movement_number
            except ValueError:
                continue
        members.append(
            {
                "id": row.id,
                "reference": row.reference_raw,
                "owner_name": names.get(row.owner_id),
                "status": row.status,
                "movement_number": number,
                "is_current": row.id == current.id,
                "linked": row.id == root.id or row.parent_shipment_id == root.id,
            }
        )
    members.sort(key=lambda row: (row["movement_number"] or 0, str(row["id"])))
    eligible = False
    try:
        eligible = (
            parse_reference(root.reference_raw or "").movement_number is None
            and root.parent_shipment_id is None
        )
    except ValueError:
        pass
    return {
        "can_add_movements": eligible
        and root.status != "CANCELLED"
        and user.role in {"OPERATOR", "SUPER_ADMIN"}
        and (user.role == "SUPER_ADMIN" or root.owner_id == user.id),
        "root": ShipmentRead.model_validate(root),
        "members": members,
        "classification": {
            "process": root.process_code,
            "operation": root.operation_code,
            "year": root.reference_year,
            "business_unit": root.business_unit,
            "department": root.department_code,
        },
    }


@router.get("/workspace/overview")
def overview(session: DB, user: Actor, month: str):
    from datetime import date

    try:
        period = date.fromisoformat(month)
        if period.day != 1:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Selecciona un mes válido") from None
    balances = balance_rows(session, user, period)
    active = session.scalar(
        owned(
            select(func.count()).select_from(Shipment).where(Shipment.status != "CANCELLED"), user
        )
    )
    invoices = finance_scope(
        select(Invoice.id, Invoice.status)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .join(Shipment, Shipment.id == InvoiceLine.shipment_id)
        .where(Invoice.accounting_period == period),
        user,
    ).distinct()
    invoice_rows = session.execute(invoices).all()
    recent = session.execute(
        owned(select(Shipment, User.display_name).join(User, User.id == Shipment.owner_id), user)
        .order_by(Shipment.updated_at.desc(), Shipment.id)
        .limit(6)
    ).all()
    return financial_json(
        {
            "month": period,
            "active_references": active,
            "live_provisions": sum(b["status"] in {"OPEN", "PARTIALLY_MATCHED"} for b in balances),
            "settled_provisions": sum(b["status"] == "CLOSED" for b in balances),
            "invoices_in_month": len(invoice_rows),
            "pending_invoices": sum(status == "UNDER_REVIEW" for _, status in invoice_rows),
            "totals": totals(balances),
            "recent": [
                {
                    "id": s.id,
                    "reference": s.reference_raw,
                    "owner_name": name,
                    "business_unit": s.business_unit,
                    "status": s.status,
                    "updated_at": s.updated_at,
                }
                for s, name in recent
            ],
        }
    )
