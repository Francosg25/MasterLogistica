"""Read the consolidated XLSX without executing formulas or loading external links."""

import hashlib
import io
import posixpath
import re
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree import ElementTree as ET

MAX_FILE = 10 * 1024 * 1024
MAX_ROWS = 20000
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MONEY = Decimal("0.0001")


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).upper().split())


def money(value):
    try:
        result = Decimal(str(value).strip().replace(",", "").replace("$", ""))
        if not result.is_finite() or abs(result) >= Decimal("100000000000000"):
            raise ValueError("Importe fuera de rango")
        return result.quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError):
        raise ValueError(
            "USD AMOUNT vacío o no numérico; guarda el Excel con sus fórmulas calculadas"
        ) from None


def invoice_date(value, date1904=False):
    if not value:
        raise ValueError("Falta INVOICE DATE")
    if re.fullmatch(r"\d+(\.\d+)?", str(value)):
        base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
        result = (base + timedelta(days=float(value))).date()
    else:
        result = None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                result = datetime.strptime(str(value).strip(), fmt).date()
                break
            except ValueError:
                pass
        if result is None:
            raise ValueError("INVOICE DATE no es una fecha válida (usa dd/mm/aaaa)")
    if not date(1990, 1, 1) <= result <= date(2100, 12, 31):
        raise ValueError("INVOICE DATE fuera de rango")
    return result.isoformat()


def read_consolidated(content):
    if len(content) > MAX_FILE:
        raise ValueError("El archivo supera 10 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ValueError("Selecciona un archivo .xlsx válido") from None
    with archive:
        members = archive.infolist()
        if len(members) > 2000 or sum(x.file_size for x in members) > 100 * 1024 * 1024:
            raise ValueError("El contenido descomprimido supera el límite de lectura")
        if len({x.filename for x in members}) != len(members):
            raise ValueError("El archivo contiene entradas duplicadas")

        def xml(path):
            raw = archive.read(path)
            # DTD/entity declarations are not part of the XLSX cell format.
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("XML no permitido en el archivo")
            return ET.fromstring(raw)

        try:
            workbook = xml("xl/workbook.xml")
            properties = workbook.find("s:workbookPr", NS)
            date1904 = properties is not None and properties.get("date1904") in {"1", "true"}
            sheets = workbook.findall("s:sheets/s:sheet", NS)
            sheet = next(
                (s for s in sheets if normalized(s.get("name")) == "CONSOLIDADO 2026"), None
            )
            if sheet is None:
                sheet = next(
                    (s for s in sheets if normalized(s.get("name", "")).startswith("CONSOLIDADO ")),
                    None,
                )
            if sheet is None:
                raise ValueError("No se encontró la hoja CONSOLIDADO 2026 o CONSOLIDADO <año>")
            relationships = {r.get("Id"): r for r in xml("xl/_rels/workbook.xml.rels")}
            relation = relationships[sheet.get(RID)]
            if relation.get("TargetMode") == "External":
                raise ValueError("No se permiten hojas externas")
            target = relation.get("Target", "")
            path = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else "xl/" + target
            )
            if not path.startswith("xl/worksheets/"):
                raise ValueError("Ruta de hoja inválida")
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = [
                    "".join(t.text or "" for t in si.findall(".//s:t", NS))
                    for si in xml("xl/sharedStrings.xml")
                ]
            data = xml(path)
            headers, records = {}, []
            for row in data.findall("s:sheetData/s:row", NS):
                row_no = int(row.get("r", "0"))
                if row_no > MAX_ROWS + 1:
                    raise ValueError("La hoja supera 20,000 filas")
                values, formulas = {}, {}
                for cell in row.findall("s:c", NS):
                    col = re.sub(r"\d", "", cell.get("r", ""))
                    node = cell.find("s:v", NS)
                    value = node.text if node is not None else None
                    if cell.get("t") == "s":
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                    values[col] = value
                    formula = cell.find("s:f", NS)
                    if formula is not None:
                        formulas[col] = formula.text or ""
                if row_no == 1:
                    # First TYPE is the charge concept; the second is transport operation.
                    for col, value in values.items():
                        headers.setdefault(normalized(value), col)
                    required = {
                        "MXT/MXG",
                        "SUPPLIER",
                        "TYPE",
                        "REFERENCIA",
                        "INVOICE #",
                        "INVOICE DATE",
                        "USD AMOUNT",
                    }
                    missing = required - headers.keys()
                    if missing:
                        raise ValueError("Faltan columnas: " + ", ".join(sorted(missing)))
                    continue

                def get(name, values=values):
                    return values.get(headers.get(name))

                if not any(get(name) for name in ("INVOICE #", "REFERENCIA", "SUPPLIER")):
                    continue
                problems = []
                try:
                    amount = money(get("USD AMOUNT"))
                    if amount <= 0:
                        problems.append(
                            "Importe cero o negativo: revisar reparto o nota de crédito"
                        )
                except ValueError as error:
                    amount = None
                    problems.append(str(error))
                try:
                    issued = invoice_date(get("INVOICE DATE"), date1904)
                except (ValueError, OverflowError):
                    issued = None
                    problems.append("Revisar INVOICE DATE; usa una fecha Excel o dd/mm/aaaa")
                concept = normalized(get("TYPE"))
                if concept not in {"FREIGHT", "BROKER", "STORAGE", "OTHER"}:
                    problems.append("Concepto TYPE no reconocido")
                if not get("INVOICE #"):
                    problems.append("Falta INVOICE #")
                records.append(
                    dict(
                        row=row_no,
                        company=normalized(get("MXT/MXG")),
                        supplier=str(get("SUPPLIER") or "").strip(),
                        invoice_number=str(get("INVOICE #") or "").strip(),
                        reference=str(get("REFERENCIA") or "").strip(),
                        charge_code=concept,
                        usd_amount=str(amount) if amount is not None else None,
                        issue_date=issued,
                        errors=problems,
                        source={
                            name: get(name)
                            for name in (
                                "ITEM",
                                "WEEK",
                                "MOUTH",
                                "CURRENCY",
                                "SUB-TOTAL",
                                "IVA",
                                "RETENTION",
                                "PAGO DE IMPUESTOS",
                                "PAGO A TERCEROS",
                                "TOTAL",
                                "USD AMOUNT",
                                "PRO NUMBER/ TRACKING #",
                                "PEDIMENTO",
                            )
                        },
                        usd_formula=formulas.get(headers["USD AMOUNT"]),
                    )
                )
        except (KeyError, IndexError, TypeError, ET.ParseError, zipfile.BadZipFile) as error:
            raise ValueError("No se pudo leer la estructura del XLSX") from error
    if not records:
        raise ValueError("La hoja no contiene movimientos")
    return {
        "sheet": sheet.get("name"),
        "sha256": hashlib.sha256(content).hexdigest(),
        "rows": records,
    }
