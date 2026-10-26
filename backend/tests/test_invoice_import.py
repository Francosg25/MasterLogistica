"""Synthetic XLSX fixtures and financial import invariants; no operational data."""

import base64
import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

import pytest
from fastapi import HTTPException

from app.invoice_excel import read_consolidated
from tests.test_finance import api, balances, provision
from tests.test_integration import create_shipment

pytest_plugins = ["tests.test_integration"]


def workbook(
    rows=None, *, formula=False, no_cache=False, usd="500", reference="RM1-0001SI26-M23-MAT"
):
    headers = [
        "MXT/MXG",
        "SUPPLIER",
        "TYPE",
        "REFERENCIA ",
        "INVOICE #",
        "INVOICE DATE",
        "MOUTH",
        "CURRENCY",
        "TOTAL",
        "USD AMOUNT",
        "SUB-TOTAL",
        "IVA",
        "TYPE",
    ]
    rows = rows or [
        [
            "JE_MX",
            "Example Test Carrier",
            "Freight",
            reference,
            "XLS-001",
            "10/10/2026",
            "OCTUBRE",
            "MXN",
            "9000",
            usd,
            "7000",
            "2000",
            "SEA IMPO",
        ]
    ]
    sheet = []
    for i, row in enumerate([headers, *rows], 1):
        cells = []
        for j, value in enumerate(row):
            address = chr(65 + j) + str(i)
            if i > 1 and j == 9 and formula:
                cells.append(
                    f'<c r="{address}"><f>I{i}/18</f>{"" if no_cache else "<v>" + str(value) + "</v>"}</c>'
                )
            else:
                cells.append(
                    f'<c r="{address}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        sheet.append(f'<row r="{i}">{"".join(cells)}</row>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="CONSOLIDADO 2026" sheetId="1" r:id="r1" /></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml" /></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(sheet)
            + "</sheetData></worksheet>",
        )
    return buffer.getvalue()


def payload(content, **changes):
    return dict(
        filename="synthetic.xlsx",
        content_base64=base64.b64encode(content).decode(),
        period_month="2026-10-01",
        **changes,
    )


def test_parser_uses_full_cached_usd_amount_without_recalculation():
    row = read_consolidated(workbook(formula=True))["rows"][0]
    assert row["usd_amount"] == "500.0000"
    assert row["source"]["SUB-TOTAL"] == "7000"
    assert row["source"]["TOTAL"] == "9000"
    assert row["charge_code"] == "FREIGHT"  # first TYPE, not transport mode
    assert row["usd_formula"] == "I2/18"
    assert row["issue_date"] == "2026-10-10"


@pytest.mark.parametrize("concept", ["OTHER", "Other", "OTROS", "otros"])
def test_other_labels_share_the_import_concept(concept):
    row = read_consolidated(
        workbook(
            rows=[
                [
                    "JE_MX",
                    "Example Test Carrier",
                    concept,
                    "REF-EXAMPLE",
                    "F-OTHER",
                    "10/10/2026",
                    "OCTUBRE",
                    "USD",
                    "100",
                    "100",
                    "100",
                    "0",
                    "SEA IMPO",
                ]
            ]
        )
    )["rows"][0]
    assert row["charge_code"] == "OTHER"
    assert row["usd_amount"] == "100.0000" and not row["errors"]


@pytest.mark.parametrize("usd", ["", "NaN", "Infinity", "-20", "0", "#DIV/0!"])
def test_invalid_amounts_require_review(usd):
    assert read_consolidated(workbook(usd=usd))["rows"][0]["errors"]


def test_formula_without_cached_result_requires_review():
    row = read_consolidated(workbook(formula=True, no_cache=True))["rows"][0]
    assert row["usd_amount"] is None and row["errors"]


def test_non_xlsx_is_rejected():
    with pytest.raises(ValueError, match="xlsx"):
        read_consolidated(b"not a workbook")


@pytest.mark.integration
def test_usd_import_closes_provision_retains_evidence_and_is_idempotent(environment):
    e = environment
    shipment = create_shipment(e)
    provision(e, shipment, month="2026-09-01")
    api(e, "post", "/periods?period_month=2026-10-01", expected=201)
    data = payload(workbook(reference=shipment["reference_raw"], formula=True))
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["READY"] == 1
    data["selected"] = [preview["groups"][0]["key"]]
    result = api(e, "post", "/import/confirm", data, expected=201)
    assert result["imported"] == 1
    assert Decimal(balances(e)["items"][0]["closing_amount"]) == 0
    inv = api(e, "get", "/invoices")["items"][0]
    assert inv["currency"] == "USD" and inv["amount_basis"] == "USD_AMOUNT"
    assert Decimal(inv["net_amount"]) == 500 and Decimal(inv["tax_amount"]) == 0
    assert inv["source_data"]["rows"][0]["source"]["TOTAL"] == "9000"
    assert api(e, "post", "/import/preview", data)["counts"]["DUPLICATE"] == 1
    api(e, "post", "/import/confirm", data, expected=409)
    activity = api(e, "get", f"/references/{shipment['id']}/activity")
    assert activity["invoices"][0]["amount_basis"] == "USD_AMOUNT"
    assert any(h["event_type"] == "INVOICE_MATCHED" for h in activity["history"]["items"])
    api(e, "get", f"/references/{shipment['id']}/activity", role="two", expected=404)


@pytest.mark.integration
def test_import_partial_balance_and_other_month(environment):
    e = environment
    shipment = create_shipment(e)
    provision(e, shipment)
    data = payload(workbook(reference=shipment["reference_raw"], usd="300"))
    preview = api(e, "post", "/import/preview", data)
    data["selected"] = [preview["groups"][0]["key"]]
    api(e, "post", "/import/confirm", data, expected=201)
    assert Decimal(balances(e, "2026-11-01")["items"][0]["closing_amount"]) == 200
    data["period_month"] = "2026-11-01"
    assert api(e, "post", "/import/preview", data)["counts"]["OUTSIDE"] == 1


@pytest.mark.integration
def test_invoice_with_zero_allocation_is_blocked_as_a_whole(environment):
    e = environment
    first, second = create_shipment(e), create_shipment(e)
    provision(e, first)
    rows = [
        [
            "JE_MX",
            "Example Test Carrier",
            "Freight",
            s["reference_raw"],
            "MULTI",
            "10/10/2026",
            "OCTUBRE",
            "USD",
            a,
            a,
        ]
        for s, a in [(first, "500"), (second, "0")]
    ]
    data = payload(workbook(rows))
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["REVIEW"] == 1
    data["selected"] = [preview["groups"][0]["key"]]
    api(e, "post", "/import/confirm", data, expected=409)
    assert api(e, "get", "/invoices")["total"] == 0


@pytest.mark.integration
def test_company_and_supplier_must_be_explicitly_mapped(environment):
    e = environment
    s = create_shipment(e)
    rows = [
        [
            "MXG",
            "Alias de proveedor",
            "Freight",
            s["reference_raw"],
            "MAP-01",
            "10/10/2026",
            "OCTUBRE",
            "USD",
            "500",
            "500",
        ]
    ]
    data = payload(workbook(rows))
    assert api(e, "post", "/import/preview", data)["counts"]["REVIEW"] == 1
    data.update(
        company_map={"MXG": "JE_MX"}, supplier_map={"ALIAS DE PROVEEDOR": str(e["supplier_id"])}
    )
    assert api(e, "post", "/import/preview", data)["counts"]["READY"] == 1
    api(e, "post", "/import/preview", data, role="one", expected=403)


@pytest.mark.integration
@pytest.mark.parametrize(
    "amount,month", [("300", "OCTUBRE"), ("0", "OCTUBRE"), ("300", "NOVIEMBRE")]
)
def test_mapped_invoice_collision_never_imports_a_partial_group(environment, amount, month):
    e = environment
    shipment = create_shipment(e)
    rows = [
        [
            "JE_MX",
            supplier,
            "Freight",
            shipment["reference_raw"],
            "SAME-01",
            "10/10/2026",
            period,
            "USD",
            value,
            value,
        ]
        for supplier, value, period in [
            ("Example Test Carrier", "500", "OCTUBRE"),
            ("Alias de proveedor", amount, month),
        ]
    ]
    data = payload(workbook(rows), supplier_map={"ALIAS DE PROVEEDOR": str(e["supplier_id"])})
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["READY"] == 0
    assert all(any("misma factura" in issue for issue in g["issues"]) for g in preview["groups"])
    data["selected"] = [g["key"] for g in preview["groups"]]
    api(e, "post", "/import/confirm", data, expected=409)
    assert api(e, "get", "/invoices")["total"] == 0


@pytest.mark.integration
def test_batch_failure_rolls_back_invoices_allocations_and_audit(environment, monkeypatch):
    from app import invoice_import

    e = environment
    shipment = create_shipment(e)
    provision(e, shipment)
    rows = [
        [
            "JE_MX",
            "Example Test Carrier",
            "Freight",
            shipment["reference_raw"],
            number,
            "10/10/2026",
            "OCTUBRE",
            "USD",
            "100",
            "100",
        ]
        for number in ("BATCH-01", "BATCH-02")
    ]
    data = payload(workbook(rows))
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["READY"] == 2
    data["selected"] = [g["key"] for g in preview["groups"]]
    register = invoice_import.register_invoice
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(409, "Synthetic concurrent update")
        return register(*args, **kwargs)

    monkeypatch.setattr(invoice_import, "register_invoice", fail_second)
    api(e, "post", "/import/confirm", data, expected=409)
    assert calls == 2
    assert api(e, "get", "/invoices")["total"] == 0
    assert Decimal(balances(e)["items"][0]["closing_amount"]) == 500
    events = api(e, "get", f"/references/{shipment['id']}/activity")["history"]["items"]
    assert not any(h["event_type"].startswith("INVOICE_") for h in events)
