from dataclasses import asdict
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.auth import admin_user, consolidated, current_user, operational_user
from app.db import get_session
from app.models import (
    AccountingPeriod,
    Provision,
    ReconciliationLog,
    ReferenceCounter,
    Shipment,
    ShipmentIdentifier,
    Supplier,
    User,
)
from app.references import (
    DEPARTMENTS,
    OPERATIONS,
    PROCESSES,
    VERSION,
    generate_reference,
    normalize_identifier,
    parse_reference,
)
from app.schemas import (
    AuditRead,
    IdentifierCreate,
    IdentifierRead,
    Page,
    PeriodCreate,
    PeriodRead,
    ProvisionCreate,
    ProvisionPatch,
    ProvisionRead,
    ReferenceInput,
    ShipmentCreate,
    ShipmentPatch,
    ShipmentRead,
    SupplierCreate,
    SupplierPatch,
    SupplierRead,
    UserCreate,
    UserPatch,
    UserRead,
    validate_total,
)

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_session)]
Actor = Annotated[User, Depends(current_user)]
Writer = Annotated[User, Depends(operational_user)]
Admin = Annotated[User, Depends(admin_user)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1000000)]
ADMIN_LOCK = 638917240


def owned(statement, user):
    return statement if consolidated(user) else statement.where(Shipment.owner_id == user.id)


def shipment_for(session, user, shipment_id):
    shipment = session.scalar(owned(select(Shipment).where(Shipment.id == shipment_id), user))
    if shipment is None:
        raise HTTPException(404, "Shipment not found")
    return shipment


def version_matches(row, expected):
    if row.row_version != expected:
        raise HTTPException(409, "Record changed; reload and retry with its current version")


def page(session, statement, schema, limit, offset):
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = session.scalars(statement.limit(limit).offset(offset)).all()
    return {
        "items": [schema.model_validate(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def record_change(
    session, request, user, action, obj, schema, *, before=None, shipment_id=None, provision_id=None
):
    try:
        session.flush([obj])
        session.flush()
        session.add(
            ReconciliationLog(
                actor_user_id=user.id,
                event_type=action,
                severity="GREEN",
                rule_version="PHASE2_V1",
                shipment_id=shipment_id,
                provision_id=provision_id,
                before_values=before or {},
                after_values=schema.model_validate(obj).model_dump(mode="json"),
                request_id=UUID(request.state.request_id),
            )
        )
        session.commit()
        session.refresh(obj)
    except StaleDataError:
        session.rollback()
        raise HTTPException(409, "Record changed; reload and retry") from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Duplicate record or conflicting database constraint") from None
    except DataError:
        session.rollback()
        raise HTTPException(422, "Values exceed supported database precision") from None
    return obj


def supplier_valid(session, supplier_id):
    if supplier_id is None:
        return
    supplier = session.get(Supplier, supplier_id)
    if supplier is None or not supplier.is_active:
        raise HTTPException(422, "Supplier does not exist or is inactive")


def open_period(session, month):
    period = session.scalar(
        select(AccountingPeriod)
        .where(AccountingPeriod.period_month == month)
        .with_for_update(read=True)
    )
    if period is None or period.status != "OPEN":
        raise HTTPException(409, "Provision requires an existing open accounting period")
    return period


@router.get("/auth/config", tags=["Authentication"])
def auth_config(request: Request):
    s = request.app.state.settings
    enabled = s.entra_configured and s.entra_frontend_client_id in s.entra_allowed_client_ids
    return {
        "enabled": enabled,
        "authority": s.authority if enabled else None,
        "api_client_id": str(s.entra_api_client_id) if enabled else None,
        "frontend_client_id": str(s.entra_frontend_client_id)
        if s.entra_frontend_client_id
        else None,
        "scope": f"api://{s.entra_api_client_id}/{s.entra_required_scope}" if enabled else None,
    }


@router.get("/auth/me", response_model=UserRead, tags=["Authentication"])
def me(user: Actor):
    return user


@router.get("/references/catalogs", tags=["References"])
def reference_catalogs(request: Request, user: Actor):
    return {
        "version": VERSION,
        "process_codes": sorted(PROCESSES),
        "operation_codes": sorted(OPERATIONS),
        "department_codes": sorted(DEPARTMENTS),
        "business_units": request.app.state.settings.business_units,
        "business_units_configured": bool(request.app.state.settings.business_units),
        "sequence_digits": 4,
        "company_codes": request.app.state.settings.company_codes,
    }


@router.post("/references/normalize", tags=["References"])
def reference_normalize(data: ReferenceInput, request: Request, user: Actor):
    try:
        parsed = parse_reference(data.raw_value)
        catalog = request.app.state.settings.business_units
        return {
            **asdict(parsed),
            "normalization_version": VERSION,
            "business_units_configured": bool(catalog),
            "business_unit_registered": parsed.business_unit in catalog if catalog else None,
        }
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/users", response_model=Page[UserRead], tags=["Administration"])
def users(session: DB, user: Admin, limit: Limit = 50, offset: Offset = 0):
    return page(session, select(User).order_by(User.created_at, User.id), UserRead, limit, offset)


@router.post("/users", response_model=UserRead, status_code=201, tags=["Administration"])
def create_user(data: UserCreate, request: Request, session: DB, user: Admin):
    tenant_id = request.app.state.settings.entra_tenant_id
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK})
    row = User(entra_tenant_id=tenant_id, **data.model_dump(exclude={"last_reference_sequence"}))
    session.add(row)
    # Flush inside record_change catches uniqueness failures. Counter references a preassigned UUID.
    from uuid import uuid4

    row.id = uuid4()
    if data.analyst_code is not None:
        session.add(ReferenceCounter(owner_id=row.id, last_value=data.last_reference_sequence))
    return record_change(session, request, user, "USER_CREATED", row, UserRead)


@router.patch("/users/{user_id}", response_model=UserRead, tags=["Administration"])
def patch_user(user_id: UUID, data: UserPatch, request: Request, session: DB, user: Admin):
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK})
    row = session.get(User, user_id)
    if row is None:
        raise HTTPException(404, "User not found")
    version_matches(row, data.expected_version)
    updates = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    losing_admin = updates.get("role", row.role) != "SUPER_ADMIN" or not updates.get(
        "is_active", row.is_active
    )
    if row.role == "SUPER_ADMIN" and row.is_active and losing_admin:
        others = session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.id != row.id, User.role == "SUPER_ADMIN", User.is_active.is_(True))
        )
        if not others:
            raise HTTPException(409, "At least one active Super Admin must remain")
    before = UserRead.model_validate(row).model_dump(mode="json")
    for key, value in updates.items():
        setattr(row, key, str(value) if key == "email" else value)
    return record_change(session, request, user, "USER_UPDATED", row, UserRead, before=before)


@router.get("/suppliers", response_model=Page[SupplierRead], tags=["Catalogs"])
def suppliers(session: DB, user: Actor, limit: Limit = 50, offset: Offset = 0):
    return page(session, select(Supplier).order_by(Supplier.code), SupplierRead, limit, offset)


@router.post("/suppliers", response_model=SupplierRead, status_code=201, tags=["Catalogs"])
def create_supplier(data: SupplierCreate, request: Request, session: DB, user: Admin):
    row = Supplier(**data.model_dump())
    session.add(row)
    return record_change(session, request, user, "SUPPLIER_CREATED", row, SupplierRead)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierRead, tags=["Catalogs"])
def patch_supplier(
    supplier_id: UUID, data: SupplierPatch, request: Request, session: DB, user: Admin
):
    row = session.get(Supplier, supplier_id)
    if row is None:
        raise HTTPException(404, "Supplier not found")
    version_matches(row, data.expected_version)
    before = SupplierRead.model_validate(row).model_dump(mode="json")
    for key, value in data.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        setattr(row, key, value)
    return record_change(
        session, request, user, "SUPPLIER_UPDATED", row, SupplierRead, before=before
    )


@router.get("/periods", response_model=Page[PeriodRead], tags=["Catalogs"])
def periods(session: DB, user: Actor, limit: Limit = 50, offset: Offset = 0):
    return page(
        session,
        select(AccountingPeriod).order_by(AccountingPeriod.period_month.desc()),
        PeriodRead,
        limit,
        offset,
    )


@router.post("/periods", response_model=PeriodRead, status_code=201, tags=["Catalogs"])
def create_period(data: PeriodCreate, request: Request, session: DB, user: Admin):
    row = AccountingPeriod(period_month=data.period_month, status="OPEN")
    session.add(row)
    return record_change(session, request, user, "PERIOD_CREATED", row, PeriodRead)


def filtered_shipments(
    user: Actor,
    q: Annotated[str | None, Query(max_length=200)] = None,
    operation_code: str | None = None,
    status: str | None = None,
    business_unit: str | None = None,
    company_code: str | None = None,
    owner_id: UUID | None = None,
    ship_date_from: date | None = None,
    ship_date_to: date | None = None,
):
    if ship_date_from and ship_date_to and ship_date_from > ship_date_to:
        raise HTTPException(422, "Start date must not be after end date")
    statement = owned(select(Shipment), user)
    for column, value in (
        (Shipment.operation_code, operation_code),
        (Shipment.status, status),
        (Shipment.business_unit, business_unit),
        (Shipment.company_code, company_code),
        (Shipment.owner_id, owner_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if q and q.strip():
        value = q.strip()
        identifiers = select(ShipmentIdentifier.shipment_id).where(
            ShipmentIdentifier.raw_value.icontains(value, autoescape=True)
        )
        statement = statement.where(
            or_(
                Shipment.reference_raw.icontains(value, autoescape=True),
                Shipment.sender.icontains(value, autoescape=True),
                Shipment.consignee.icontains(value, autoescape=True),
                Shipment.id.in_(identifiers),
            )
        )
    if ship_date_from:
        statement = statement.where(Shipment.ship_date >= ship_date_from)
    if ship_date_to:
        statement = statement.where(Shipment.ship_date <= ship_date_to)
    return statement


@router.get("/masters/owners", tags=["Masters"])
def master_owners(session: DB, user: Actor):
    statement = select(User).order_by(User.display_name, User.id)
    if not consolidated(user):
        statement = statement.where(User.id == user.id)
    return [{"id": row.id, "display_name": row.display_name} for row in session.scalars(statement)]


@router.get("/shipments/summary", tags=["Masters"])
def shipment_summary(session: DB, statement=Depends(filtered_shipments)):
    rows = statement.order_by(None).subquery()
    counts = dict(
        session.execute(select(rows.c.status, func.count()).group_by(rows.c.status)).all()
    )
    return {"total": sum(counts.values()), "by_status": counts}


@router.get("/shipments", response_model=Page[ShipmentRead], tags=["Masters"])
def shipments(
    session: DB,
    limit: Limit = 50,
    offset: Offset = 0,
    statement=Depends(filtered_shipments),
):
    return page(
        session,
        statement.order_by(Shipment.created_at.desc(), Shipment.id),
        ShipmentRead,
        limit,
        offset,
    )


@router.get("/shipments/{shipment_id}", response_model=ShipmentRead, tags=["Masters"])
def shipment_detail(shipment_id: UUID, session: DB, user: Actor):
    return shipment_for(session, user, shipment_id)


@router.post("/shipments", response_model=ShipmentRead, status_code=201, tags=["Masters"])
def create_shipment(data: ShipmentCreate, request: Request, session: DB, user: Writer):
    if data.company_code not in request.app.state.settings.company_codes:
        raise HTTPException(422, "Company code is not configured")
    catalog = request.app.state.settings.business_units
    if not catalog:
        raise HTTPException(503, "An approved business unit catalog must be configured")
    if data.business_unit not in catalog:
        raise HTTPException(422, "Business unit is not in the approved catalog")
    supplier_valid(session, data.carrier_broker_id)
    supplier_valid(session, data.shipping_line_id)
    try:
        reference, sequence = generate_reference(
            session,
            user,
            process=data.process_code,
            operation=data.operation_code,
            year=data.reference_year,
            business_unit=data.business_unit,
            department=data.department_code,
            business_units=catalog,
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    mode, service, direction = OPERATIONS[data.operation_code]
    row = Shipment(
        **data.model_dump(),
        owner_id=user.id,
        reference_raw=reference,
        reference_normalized=reference,
        normalization_version=VERSION,
        reference_sequence=sequence,
        transport_mode=mode,
        service_category=service,
        direction=direction,
    )
    from uuid import uuid4

    row.id = uuid4()
    session.add(row)
    session.add(
        ShipmentIdentifier(
            shipment_id=row.id,
            kind="REFERENCE",
            raw_value=reference,
            normalized_value=reference,
            normalization_version=VERSION,
        )
    )
    return record_change(
        session, request, user, "SHIPMENT_CREATED", row, ShipmentRead, shipment_id=row.id
    )


def add_reference_alias(session, row, suffix):
    if row.reference_normalized is None:
        raise HTTPException(
            409, "Shipment requires a normalized base reference before adding aliases"
        )
    value = f"{row.reference_normalized}.{suffix}"
    existing = session.scalar(
        select(ShipmentIdentifier.id).where(
            ShipmentIdentifier.shipment_id == row.id,
            ShipmentIdentifier.kind == "REFERENCE",
            ShipmentIdentifier.normalized_value == value,
        )
    )
    if existing is None:
        session.add(
            ShipmentIdentifier(
                shipment_id=row.id,
                kind="REFERENCE",
                raw_value=value,
                normalized_value=value,
                normalization_version=row.normalization_version or VERSION,
            )
        )


@router.patch("/shipments/{shipment_id}", response_model=ShipmentRead, tags=["Masters"])
def patch_shipment(
    shipment_id: UUID, data: ShipmentPatch, request: Request, session: DB, user: Writer
):
    row = shipment_for(session, user, shipment_id)
    version_matches(row, data.expected_version)
    updates = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    for field in {"carrier_broker_id", "shipping_line_id"} & updates.keys():
        supplier_valid(session, updates[field])
    expedited = updates.get("expedited_status", row.expedited_status)
    approval = updates.get("pfa_approval_code", row.pfa_approval_code)
    if (expedited == "APPROVED") != bool(approval):
        raise HTTPException(
            422,
            "Approved expedited status requires a PFA approval code; other statuses must clear it",
        )
    before = ShipmentRead.model_validate(row).model_dump(mode="json")
    for key, value in updates.items():
        setattr(row, key, value)
    # Avoid autoflush: all writes, constraints and audit commit are handled atomically below.
    with session.no_autoflush:
        if row.damaged_material:
            add_reference_alias(session, row, "DMR")
        if expedited == "PENDING":
            add_reference_alias(session, row, "PFA")
        elif expedited == "APPROVED":
            add_reference_alias(session, row, approval)
    return record_change(
        session,
        request,
        user,
        "SHIPMENT_UPDATED",
        row,
        ShipmentRead,
        before=before,
        shipment_id=row.id,
    )


@router.get(
    "/shipments/{shipment_id}/identifiers", response_model=list[IdentifierRead], tags=["Masters"]
)
def identifiers(shipment_id: UUID, session: DB, user: Actor):
    shipment_for(session, user, shipment_id)
    return session.scalars(
        select(ShipmentIdentifier)
        .where(ShipmentIdentifier.shipment_id == shipment_id)
        .order_by(ShipmentIdentifier.kind, ShipmentIdentifier.normalized_value)
    ).all()


@router.post(
    "/shipments/{shipment_id}/identifiers",
    response_model=IdentifierRead,
    status_code=201,
    tags=["Masters"],
)
def add_identifier(
    shipment_id: UUID, data: IdentifierCreate, request: Request, session: DB, user: Writer
):
    shipment_for(session, user, shipment_id)
    try:
        normalized = normalize_identifier(data.raw_value)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    row = ShipmentIdentifier(
        shipment_id=shipment_id,
        kind=data.kind,
        raw_value=data.raw_value,
        normalized_value=normalized,
        normalization_version="IDENTIFIER_V1",
    )
    session.add(row)
    return record_change(
        session, request, user, "IDENTIFIER_ADDED", row, IdentifierRead, shipment_id=shipment_id
    )


@router.get("/provisions", response_model=Page[ProvisionRead], tags=["Provisions"])
def provisions(
    session: DB, user: Actor, limit: Limit = 50, offset: Offset = 0, shipment_id: UUID | None = None
):
    statement = owned(select(Provision).join(Shipment, Shipment.id == Provision.shipment_id), user)
    if shipment_id:
        statement = statement.where(Provision.shipment_id == shipment_id)
    return page(
        session,
        statement.order_by(Provision.created_at.desc(), Provision.id),
        ProvisionRead,
        limit,
        offset,
    )


def provision_for(session, user, provision_id):
    row = session.scalar(
        owned(
            select(Provision)
            .join(Shipment, Shipment.id == Provision.shipment_id)
            .where(Provision.id == provision_id),
            user,
        )
    )
    if row is None:
        raise HTTPException(404, "Provision not found")
    return row


@router.get("/provisions/{provision_id}", response_model=ProvisionRead, tags=["Provisions"])
def provision_detail(provision_id: UUID, session: DB, user: Actor):
    return provision_for(session, user, provision_id)


@router.post("/provisions", response_model=ProvisionRead, status_code=201, tags=["Provisions"])
def create_provision(data: ProvisionCreate, request: Request, session: DB, user: Writer):
    shipment = shipment_for(session, user, data.shipment_id)
    if shipment.status == "CANCELLED":
        raise HTTPException(409, "Cannot add provisions to a cancelled shipment")
    supplier_valid(session, data.supplier_id)
    open_period(session, data.month_accrued)
    row = Provision(**data.model_dump(), status="DRAFT")
    from uuid import uuid4

    row.id = uuid4()
    session.add(row)
    return record_change(
        session,
        request,
        user,
        "PROVISION_DRAFT_CREATED",
        row,
        ProvisionRead,
        shipment_id=row.shipment_id,
        provision_id=row.id,
    )


@router.patch("/provisions/{provision_id}", response_model=ProvisionRead, tags=["Provisions"])
def patch_provision(
    provision_id: UUID, data: ProvisionPatch, request: Request, session: DB, user: Writer
):
    row = provision_for(session, user, provision_id)
    version_matches(row, data.expected_version)
    if row.status != "DRAFT":
        raise HTTPException(409, "Only draft provisions can be edited in Phase 2")
    open_period(session, row.month_accrued)
    updates = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    try:
        validate_total(
            updates.get("amount", row.amount), updates.get("extra_charges", row.extra_charges)
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    before = ProvisionRead.model_validate(row).model_dump(mode="json")
    for key, value in updates.items():
        setattr(row, key, value)
    return record_change(
        session,
        request,
        user,
        "PROVISION_DRAFT_UPDATED",
        row,
        ProvisionRead,
        before=before,
        shipment_id=row.shipment_id,
        provision_id=row.id,
    )


@router.get("/audit", response_model=Page[AuditRead], tags=["Audit"])
def audit(session: DB, user: Actor, limit: Limit = 50, offset: Offset = 0):
    statement = select(ReconciliationLog)
    if user.role != "SUPER_ADMIN":
        statement = owned(
            statement.join(Shipment, Shipment.id == ReconciliationLog.shipment_id), user
        )
    return page(
        session,
        statement.order_by(ReconciliationLog.occurred_at.desc(), ReconciliationLog.id),
        AuditRead,
        limit,
        offset,
    )
