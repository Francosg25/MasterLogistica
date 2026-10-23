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
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, ValidationError
from sqlalchemy import select

from app.api import DB, open_period
from app.finance import FinanceWriter, commit, financial_json, lock_shipments, register_invoice
from app.finance_schemas import InvoiceCreate
from app.invoice_excel import normalized, read_consolidated
from app.models import Invoice, Shipment, ShipmentIdentifier, Supplier
from app.references import normalize_identifier, parse_reference
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
    company_map: Annotated[dict[str, str], Field(max_length=100)] = {}
    supplier_map: Annotated[dict[str, UUID], Field(max_length=1000)] = {}
    selected: Annotated[list[str], Field(max_length=100)] = []


def reference_key(value):
    try:
        return parse_reference(value).normalized
    except ValueError:
        return "".join(normalized(value).split())


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
    suppliers = session.scalars(select(Supplier).where(Supplier.is_active.is_(True))).all()
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
    by_shipment = {s.id: s for s in shipments}
    for shipment in shipments:
        by_ref[(shipment.company_code, shipment.reference_normalized)].add(shipment.id)
    for alias in session.scalars(
        select(ShipmentIdentifier).where(ShipmentIdentifier.kind == "REFERENCE")
    ):
        shipment = by_shipment.get(alias.shipment_id)
        if shipment:
            by_ref[(shipment.company_code, alias.normalized_value)].add(shipment.id)
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
        if supplier and company in companies:
            destinations[(company, supplier_id, number)].append(key)
        issues = [f"Fila {r['row']}: {error}" for r in rows for error in r["errors"]]
        source_months = {MONTHS.get(normalized(r["source"].get("MOUTH"))) for r in rows}
        outside = bool(
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
        if not supplier:
            issues.append("Vincula el proveedor con un proveedor activo del catálogo")
        if len({r["issue_date"] for r in rows}) != 1:
            issues.append("La factura tiene fechas distintas entre sus movimientos")
        if len(rows) > 100:
            issues.append("La factura supera 100 movimientos")
        lines = []
        for row in rows:
            ref = reference_key(row["reference"])
            matches = by_ref.get((company, ref), set())
            if len(matches) != 1:
                issues.append(
                    f"Fila {row['row']}: referencia sin coincidencia única; corrige o registra su alias en el master"
                )
                reference = row["reference"]
            else:
                shipment = by_shipment[next(iter(matches))]
                reference = shipment.reference_raw
                if shipment.status == "CANCELLED":
                    issues.append(f"Fila {row['row']}: el embarque está cancelado")
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
                    accounting_period=data.period_month,
                    currency="USD",
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
                rows=[
                    dict(
                        row=r["row"],
                        reference=r["reference"],
                        charge_code=r["charge_code"],
                        usd_amount=r["usd_amount"],
                        issue_date=r["issue_date"],
                    )
                    for r in rows
                ],
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
    return dict(
        sheet=parsed["sheet"],
        sha256=parsed["sha256"],
        row_count=len(parsed["rows"]),
        invoice_count=len(groups),
        counts={
            status: sum(g["status"] == status for g in groups)
            for status in ("READY", "REVIEW", "DUPLICATE", "OUTSIDE")
        },
        companies=sorted({r["company"] for r in parsed["rows"]}),
        suppliers=sorted({normalized(r["supplier"]) for r in parsed["rows"]}),
        groups=[{k: v for k, v in g.items() if k != "evidence"} for g in groups],
    )


@router.post("/confirm", status_code=201)
def confirm(data: ImportRequest, session: DB, user: FinanceWriter, request: Request):
    if not data.selected or len(set(data.selected)) != len(data.selected):
        raise HTTPException(422, "Selecciona de 1 a 100 facturas distintas por lote")
    open_period(session, data.period_month)
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
        references = [
            line.reference for group in candidates for line in payloads[group["key"]].lines
        ]
        lock_shipments(
            session,
            session.scalars(
                select(Shipment.id).where(Shipment.reference_raw.in_(references))
            ).all(),
        )
        for group in sorted(candidates, key=lambda g: g["key"]):
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
