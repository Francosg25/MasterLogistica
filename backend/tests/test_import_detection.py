"""Reference detection is visible independently of invoice readiness and expense month."""

import io
import zipfile
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.models import ShipmentIdentifier
from tests.test_finance import api
from tests.test_integration import create_shipment
from tests.test_invoice_import import payload, workbook
from tests.test_local import local_financial_environment as local_financial_environment


def invoice_row(
    reference,
    month="SEPTIEMBRE",
    company="JE_MX",
    supplier="Example Test Carrier",
    number="DETECT-TEST",
):
    return [
        company,
        supplier,
        "FREIGHT",
        reference,
        number,
        "10/09/2026",
        month,
        "USD",
        "500",
        "500",
        "500",
        "0",
        "SEA IMPO",
    ]


def test_reference_is_detected_in_another_month_and_import_uses_the_selected_month(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e, department_code=None)
    data = payload(workbook(rows=[invoice_row(shipment["reference_raw"])]))
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"] == {"READY": 0, "REVIEW": 0, "DUPLICATE": 0, "OUTSIDE": 1}
    assert preview["reference_counts"]["MATCHED"] == 1
    group = preview["groups"][0]
    assert group["rows"][0]["reference_match"] == dict(
        status="MATCHED",
        shipment_id=shipment["id"],
        reference=shipment["reference_raw"],
        company="JE_MX",
        owner_name="one",
    )
    assert group["source_periods"] == ["2026-09-01"]
    assert preview["available_periods"] == [
        dict(period_month="2026-09-01", row_count=1, invoice_count=1)
    ]
    api(e, "post", "/import/confirm", {**data, "selected": [group["key"]]}, expected=409)
    data["period_month"] = "2026-09-01"
    preview = api(e, "post", "/import/preview", data)
    assert preview["counts"]["READY"] == 1
    api(e, "post", "/import/confirm", {**data, "selected": [group["key"]]}, expected=201)
    stored = api(e, "get", "/invoices")["items"][0]
    assert stored["lines"][0]["shipment_id"] == shipment["id"]
    assert stored["accounting_period"] == "2026-09-01"
    assert api(e, "post", "/import/preview", data)["counts"]["DUPLICATE"] == 1


def test_detects_reference_when_supplier_is_unknown_instead_of_hiding_the_match(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    data = payload(
        workbook(
            rows=[
                invoice_row(
                    shipment["reference_raw"], "OCTUBRE", supplier="Unknown synthetic carrier"
                )
            ]
        )
    )
    result = api(e, "post", "/import/preview", data)
    assert result["reference_counts"]["MATCHED"] == 1 and result["counts"]["REVIEW"] == 1
    assert any("proveedor" in reason for reason in result["groups"][0]["issues"])


def test_company_mismatch_is_found_but_requires_an_explicit_company_mapping(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e, company_code="MXG")
    data = payload(
        workbook(rows=[invoice_row(shipment["reference_raw"], "OCTUBRE", company="MXT")])
    )
    preview = api(e, "post", "/import/preview", data)
    group = preview["groups"][0]
    assert group["rows"][0]["reference_match"]["status"] == "OTHER_COMPANY"
    assert group["rows"][0]["reference_match"]["company"] == "MXG"
    assert preview["counts"]["READY"] == 0
    assert any("Excel indica MXT" in reason for reason in group["issues"])
    api(e, "post", "/import/confirm", {**data, "selected": [group["key"]]}, expected=409)
    mapped = api(e, "post", "/import/preview", {**data, "company_map": {"MXT": "MXG"}})
    assert mapped["counts"]["READY"] == 1
    assert mapped["groups"][0]["rows"][0]["reference_match"]["status"] == "MATCHED"


def test_detects_aliases_and_spaces_without_merging_distinct_reference_suffixes(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e, department_code=None)
    old = shipment["reference_raw"]
    renamed = e["client"].patch(
        "/api/v1/shipments/" + shipment["id"],
        headers=e["headers"]("one"),
        json={"expected_version": 1, "reference_raw": "SYNTHETIC-NEW-REFERENCE"},
    )
    assert renamed.status_code == 200
    data = payload(
        workbook(rows=[invoice_row("  " + old.lower().replace("-", "- ") + "\u00a0", "OCTUBRE")])
    )
    match = api(e, "post", "/import/preview", data)["groups"][0]["rows"][0]["reference_match"]
    assert match["status"] == "MATCHED" and match["reference"] == "SYNTHETIC-NEW-REFERENCE"
    other = payload(workbook(rows=[invoice_row(old + "-MAT", "OCTUBRE")]))
    assert api(e, "post", "/import/preview", other)["reference_counts"]["NOT_FOUND"] == 1


def test_ambiguous_legacy_alias_is_never_assigned_to_an_arbitrary_shipment(
    local_financial_environment,
):
    e = local_financial_environment
    a, b = create_shipment(e), create_shipment(e)
    from uuid import UUID

    with Session(e["admin_engine"]) as session, session.begin():
        for row in (a, b):
            session.add(
                ShipmentIdentifier(
                    shipment_id=UUID(row["id"]),
                    kind="REFERENCE",
                    raw_value="SYNTHETIC-SHARED-ALIAS",
                    normalized_value="SYNTHETIC-SHARED-ALIAS",
                    normalization_version="MANUAL",
                )
            )
    data = payload(workbook(rows=[invoice_row("SYNTHETIC-SHARED-ALIAS", "OCTUBRE")]))
    result = api(e, "post", "/import/preview", data)
    assert result["reference_counts"]["AMBIGUOUS"] == 1 and result["counts"]["READY"] == 0


def test_mixed_month_invoice_keeps_all_reference_matches_but_requires_review(
    local_financial_environment,
):
    e = local_financial_environment
    shipment = create_shipment(e)
    result = api(
        e,
        "post",
        "/import/preview",
        payload(
            workbook(
                rows=[
                    invoice_row(shipment["reference_raw"]),
                    invoice_row(shipment["reference_raw"], "OCTUBRE"),
                ]
            )
        ),
    )
    assert result["invoice_count"] == 1 and result["counts"]["REVIEW"] == 1
    assert result["reference_counts"]["MATCHED"] == 2
    assert [p["period_month"] for p in result["available_periods"]] == ["2026-09-01", "2026-10-01"]


def reference_in_column_g(reference, helper, company="JE_MX"):
    """Synthetic layout with the actual named reference column G and an unused helper F."""
    headers = [
        "ITEM",
        "MXT/MXG",
        "SUPPLIER",
        "TYPE",
        "MOUTH",
        "NO TOCAR",
        "REFERENCIA",
        "INVOICE #",
        "INVOICE DATE",
        "USD AMOUNT",
    ]
    values = [
        "1",
        company,
        "Example Test Carrier",
        "FREIGHT",
        "SEPTIEMBRE",
        helper,
        reference,
        "COLUMN-G-TEST",
        "10/09/2026",
        "500",
    ]
    rows = []
    for index, data in enumerate((headers, values), 1):
        cells = [
            f'<c r="{chr(65 + col)}{index}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            for col, value in enumerate(data)
        ]
        rows.append(f'<row r="{index}">{"".join(cells)}</row>')
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(result, "w") as target:
        for item in source.infolist():
            target.writestr(
                item.filename,
                (
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                    + "".join(rows)
                    + "</sheetData></worksheet>"
                ).encode()
                if item.filename == "xl/worksheets/sheet1.xml"
                else source.read(item.filename),
            )
    return result.getvalue()


def test_uses_reference_in_g_even_when_helper_f_contains_another_value(local_financial_environment):
    e = local_financial_environment
    shipment = create_shipment(e, department_code=None)
    found = api(
        e,
        "post",
        "/import/preview",
        payload(reference_in_column_g(shipment["reference_raw"], "FREIGHT-WRONG-HELPER")),
    )
    assert found["reference_counts"]["MATCHED"] == 1
    missing = api(
        e,
        "post",
        "/import/preview",
        payload(
            reference_in_column_g(
                "NOT-A-REGISTERED-REFERENCE", "FREIGHT" + shipment["reference_raw"]
            )
        ),
    )
    assert missing["reference_counts"]["NOT_FOUND"] == 1
