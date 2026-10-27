"""Preview and atomically import invoice batches from the consolidated XLSX."""

import base64
import binascii
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import DB
from app.finance import (
    FinanceWriter,
    audit_event,
    commit,
    ensure_period,
    financial_json,
    lock_shipments,
    register_invoice,
)
from app.finance_schemas import InvoiceCreate, SettlementFx
from app.invoice_excel import normalized, read_consolidated
from app.models import Invoice, Shipment, ShipmentIdentifier, Supplier, User
from app.references import normalize_identifier, normalize_reference
from app.schemas import Schema

router = APIRouter(prefix="/api/v1/finance/import", tags=["Invoice import"])
MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "ENERO",
            "FEBRERO",
            "MARZO",
            "ABRIL",
            "MAYO",
            "JUNIO",
            "JULIO",
            "AGOSTO",
            "SEPTIEMBRE",
            "OCTUBRE",
            "NOVIEMBRE",
            "DICIEMBRE",
        ),
        1,
    )
}


class ImportRequest(Schema):
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    content_base64: Annotated[str, Field(min_length=1, max_length=14_000_000)]
    period_month: date
    use_source_period: bool = False
    create_suppliers: bool = False
    fx: SettlementFx | None = None
    company_map: Annotated[dict[str, str], Field(max_length=100)] = {}
    supplier_map: Annotated[dict[str, UUID], Field(max_length=1000)] = {}
    selected: Annotated[list[str], Field(max_length=100)] = []


def reference_key(value):
    return normalize_reference(value)


def prepare(data, session, request):
    if data.period_month.day != 1:
        raise HTTPException(422, "Selecciona el mes contable de la importación")
    if not data.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "Solo se admite el consolidado en formato .xlsx")
    try:
        content = base64.b64decode(data.content_base64, validate=True)
        parsed = read_consolidated(content)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, str(error)) from None
    all_suppliers = session.scalars(select(Supplier)).all()
    suppliers = [s for s in all_suppliers if s.is_active]
    known_names = {normalized(name) for s in all_suppliers for name in (s.legal_name, s.code)}
    by_name = defaultdict(set)
    by_id = {str(s.id): s for s in suppliers}
    for supplier in suppliers:
        for name in (supplier.legal_name, supplier.code):
            by_name[normalized(name)].add(str(supplier.id))
    # Index authorized finance scope once instead of querying per spreadsheet row.
    shipments = session.scalars(select(Shipment)).all()
    companies = sorted(
        set(request.app.state.settings.company_codes) | {s.company_code for s in shipments}
    )
    by_ref = defaultdict(set)
    by_any_company = defaultdict(set)
    by_shipment = {s.id: s for s in shipments}
    owner_names = dict(session.execute(select(User.id, User.display_name)).all())
    for shipment in shipments:
        by_ref[(shipment.company_code, shipment.reference_normalized)].add(shipment.id)
        by_any_company[shipment.reference_normalized].add(shipment.id)
    for alias in session.scalars(
        select(ShipmentIdentifier).where(ShipmentIdentifier.kind == "REFERENCE")
    ):
        shipment = by_shipment.get(alias.shipment_id)
        if shipment:
            by_ref[(shipment.company_code, alias.normalized_value)].add(shipment.id)
            by_any_company[alias.normalized_value].add(shipment.id)
    existing = {
        (i.company_code, str(i.supplier_id), i.invoice_number_normalized)
        for i in session.scalars(select(Invoice))
    }
    grouped = defaultdict(list)
    for row in parsed["rows"]:
        try:
            number = normalize_identifier(row["invoice_number"])
        except ValueError:
            number = row["invoice_number"]
            row["errors"].append("Folio de factura inválido")
        grouped[(row["company"], normalized(row["supplier"]), number)].append(row)
    groups, payloads = [], {}
    destinations = defaultdict(list)
    year = re.search(r"\b(20\d{2})\b", parsed["sheet"])
    for (source_company, source_supplier, number), rows in grouped.items():
        key = hashlib.sha256(
            json.dumps([source_company, source_supplier, number]).encode()
        ).hexdigest()
        company = data.company_map.get(source_company, source_company)
        matched = by_name.get(source_supplier, set())
        supplier_id = str(data.supplier_map.get(source_supplier, "")) or (
            next(iter(matched)) if len(matched) == 1 else ""
        )
        supplier = by_id.get(supplier_id)
        new_supplier = None
        if (
            not supplier
            and not supplier_id
            and data.create_suppliers
            and source_supplier not in known_names
            and 0 < len(rows[0]["supplier"].strip()) <= 250
        ):
            supplier_id = str(
                uuid5(NAMESPACE_URL, "MasterLogistica:excel-supplier:" + source_supplier)
            )
            new_supplier = dict(
                id=supplier_id,
                code="XL-" + hashlib.sha256(source_supplier.encode()).hexdigest()[:32],
                legal_name=rows[0]["supplier"].strip(),
            )
        if (supplier or new_supplier) and company in companies:
            destinations[(company, supplier_id, number)].append(key)
        issues = [f"Fila {r['row']}: {error}" for r in rows for error in r["errors"]]
        source_months = {MONTHS.get(normalized(r["source"].get("MOUTH"))) for r in rows}
        outside = not data.use_source_period and bool(
            year
            and None not in source_months
            and (
                data.period_month.year != int(year[1])
                or data.period_month.month not in source_months
            )
        )
        if None in source_months or not year:
            issues.append("Revisa MOUTH y el año del nombre de la hoja")
        if len(source_months) > 1:
            issues.append(
                "La misma factura aparece en varios meses; revisa el periodo antes de importarla"
            )
        if company not in companies:
            issues.append("Vincula la compañía del Excel con una compañía configurada")
        if not supplier and not new_supplier:
            issues.append("Vincula el proveedor con un proveedor activo del catálogo")
        if len({r["issue_date"] for r in rows}) != 1:
            issues.append("La factura tiene fechas distintas entre sus movimientos")
        if len(rows) > 100:
            issues.append("La factura supera 100 movimientos")
        lines, preview_rows = [], []
        for row in rows:
            ref = reference_key(row["reference"])
            matches = by_ref.get((company, ref), set())
            candidates = matches or by_any_company.get(ref, set())
            detection = {"status": "AMBIGUOUS" if candidates else "NOT_FOUND"}
            if len(candidates) == 1:
                found = by_shipment[next(iter(candidates))]
                detection = dict(
                    status="MATCHED" if len(matches) == 1 else "OTHER_COMPANY",
                    shipment_id=str(found.id),
                    reference=found.reference_raw,
                    company=found.company_code,
                    owner_name=owner_names.get(found.owner_id),
                )
            if len(matches) != 1:
                if detection["status"] == "OTHER_COMPANY":
                    issues.append(
                        f"Fila {row['row']}: la referencia está registrada en {detection['company']}; el Excel indica {company}. Revisa la empresa"
                    )
                else:
                    issues.append(
                        f"Fila {row['row']}: referencia sin coincidencia única; corrige o registra su alias en el master"
                    )
                reference = row["reference"]
            else:
                shipment = by_shipment[next(iter(matches))]
                reference = shipment.reference_raw
                if shipment.status == "CANCELLED":
                    issues.append(f"Fila {row['row']}: el embarque está cancelado")
            month = MONTHS.get(normalized(row["source"].get("MOUTH")))
            preview_rows.append(
                dict(
                    row=row["row"],
                    reference=row["reference"],
                    charge_code=row["charge_code"],
                    usd_amount=row["usd_amount"],
                    issue_date=row["issue_date"],
                    source_period=f"{year[1]}-{month:02d}-01" if year and month else None,
                    reference_match=detection,
                )
            )
            lines.append(
                dict(
                    reference=reference,
                    charge_code=row["charge_code"],
                    net_amount=row["usd_amount"] or "0",
                    tax_amount="0",
                    description=f"USD AMOUNT completo · {parsed['sheet']} · fila {row['row']}",
                )
            )
        duplicate = (company, supplier_id, number) in existing
        if not issues and not duplicate and not outside:
            try:
                payloads[key] = InvoiceCreate(
                    supplier_id=supplier_id,
                    company_code=company,
                    invoice_number=rows[0]["invoice_number"],
                    issue_date=rows[0]["issue_date"],
                    accounting_period=date(int(year[1]), next(iter(source_months)), 1)
                    if data.use_source_period
                    else data.period_month,
                    currency="USD",
                    fx=data.fx,
                    lines=lines,
                )
            except ValidationError:
                issues.append("Revisa longitudes, folio, fecha e importes de la factura")
        groups.append(
            dict(
                key=key,
                invoice_number=rows[0]["invoice_number"],
                company=company,
                supplier_name=supplier.legal_name if supplier else rows[0]["supplier"],
                source_supplier=source_supplier,
                source_company=source_company,
                supplier_action="NEW" if new_supplier else "MATCHED" if supplier else "REVIEW",
                new_supplier=new_supplier,
                status="OUTSIDE"
                if outside
                else "DUPLICATE"
                if duplicate
                else "REVIEW"
                if issues
                else "READY",
                usd_amount=str(
                    sum((Decimal(r["usd_amount"]) for r in rows if r["usd_amount"]), Decimal(0))
                ),
                issues=issues,
                rows=preview_rows,
                source_periods=sorted(
                    {r["source_period"] for r in preview_rows if r["source_period"]}
                ),
                evidence=rows,
            )
        )
    # Include invalid/out-of-period groups: importing only the valid subset of one
    # invoice would permanently strand the other rows behind its unique identity.
    collisions = {key for keys in destinations.values() if len(keys) > 1 for key in keys}
    for group in groups:
        if group["key"] in collisions:
            if group["status"] == "READY":
                group["status"] = "REVIEW"
            payloads.pop(group["key"], None)
            group["issues"].append(
                "Dos grupos del Excel identifican la misma factura; unifica sus datos antes de importar"
            )
    return parsed, groups, payloads


@router.post("/preview")
def preview(data: ImportRequest, session: DB, user: FinanceWriter, request: Request):
    parsed, groups, _ = prepare(data, session, request)
    periods = defaultdict(lambda: {"row_count": 0, "invoices": set()})
    reference_counts = {key: 0 for key in ("MATCHED", "OTHER_COMPANY", "NOT_FOUND", "AMBIGUOUS")}
    for group in groups:
        for row in group["rows"]:
            reference_counts[row["reference_match"]["status"]] += 1
            if row["source_period"]:
                period = periods[row["source_period"]]
                period["row_count"] += 1
                period["invoices"].add(group["key"])
    return dict(
        sheet=parsed["sheet"],
        sha256=parsed["sha256"],
        row_count=len(parsed["rows"]),
        invoice_count=len(groups),
        reference_counts=reference_counts,
        available_periods=[
            dict(
                period_month=key, row_count=value["row_count"], invoice_count=len(value["invoices"])
            )
            for key, value in sorted(periods.items())
        ],
        counts={
            status: sum(g["status"] == status for g in groups)
            for status in ("READY", "REVIEW", "DUPLICATE", "OUTSIDE")
        },
        companies=sorted({r["company"] for r in parsed["rows"]}),
        suppliers=sorted({normalized(r["supplier"]) for r in parsed["rows"]}),
        groups=[
            {k: v for k, v in g.items() if k not in {"evidence", "new_supplier"}} for g in groups
        ],
    )


@router.post("/confirm", status_code=201)
def confirm(data: ImportRequest, session: DB, user: FinanceWriter, request: Request):
    if not data.selected or len(set(data.selected)) != len(data.selected):
        raise HTTPException(422, "Selecciona de 1 a 100 facturas distintas por lote")
    parsed, groups, payloads = prepare(data, session, request)
    selected = set(data.selected)
    candidates = [g for g in groups if g["key"] in selected]
    if len(candidates) != len(selected):
        raise HTTPException(422, "La selección no pertenece al archivo")
    if any(g["status"] != "READY" for g in candidates):
        raise HTTPException(
            409, "Una factura cambió, ya se importó o necesita revisión. Actualiza la vista previa"
        )
    # All-or-nothing per batch; unique invoice keys also prevent concurrent double imports.
    created = []
    try:
        for period in sorted({payloads[g["key"]].accounting_period for g in candidates}):
            ensure_period(session, user, request, period)
        for group in candidates:
            values = group["new_supplier"]
            if not values or session.get(Supplier, UUID(values["id"])):
                continue
            # Same normalized name always gets the same identity, including concurrent batches.
            try:
                with session.begin_nested():
                    supplier = Supplier(**{**values, "id": UUID(values["id"])}, is_active=True)
                    session.add(supplier)
                    session.flush()
                    audit_event(
                        session,
                        request,
                        user,
                        "SUPPLIER_CREATED",
                        after={
                            "code": supplier.code,
                            "legal_name": supplier.legal_name,
                            "source": "Excel de facturas",
                        },
                    )
            except IntegrityError:
                supplier = session.get(Supplier, UUID(values["id"]))
                if supplier is None or not supplier.is_active:
                    raise HTTPException(
                        409, "El proveedor cambió. Revisa el archivo de nuevo"
                    ) from None
        references = [
            line.reference for group in candidates for line in payloads[group["key"]].lines
        ]
        lock_shipments(
            session,
            session.scalars(
                select(Shipment.id).where(Shipment.reference_raw.in_(references))
            ).all(),
        )
        for group in sorted(
            candidates, key=lambda g: (payloads[g["key"]].accounting_period, g["key"])
        ):
            evidence = dict(
                amount_basis="USD_AMOUNT",
                filename=data.filename,
                sha256=parsed["sha256"],
                sheet=parsed["sheet"],
                row_numbers=[r["row"] for r in group["evidence"]],
                rows=group["evidence"],
                source_company=group["source_company"],
                source_supplier=group["source_supplier"],
            )
            row = register_invoice(
                payloads[group["key"]], session, user, request, source_data=evidence, persist=False
            )
            created.append(
                dict(id=row.id, invoice_number=row.invoice_number_raw, status=row.status)
            )
        commit(session)
    except Exception:
        session.rollback()
        raise
    return financial_json(dict(imported=len(created), invoices=created, amount_basis="USD_AMOUNT"))
