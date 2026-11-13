"""Invoice capture and import preserve the same manual reference key as the master."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.local_schema import LOCAL_SUPPLIER
from app.main import create_app
from app.models import InvoiceLineIdentifier
from app.references import VERSION, normalize_reference
from tests.test_catalog_cleanup import create
from tests.test_finance import invoice, provision
from tests.test_invoice_import import payload, workbook
from tests.test_local import local_client, local_settings


@pytest.mark.parametrize("reference", [
    "RM-V-9999-V1I26-M01, M46, M23",
    "Operación de prueba (México)",
    "RM-V-9999-V1I26-M01/M46",
])
@pytest.mark.parametrize("from_excel", [False, True])
def test_invoice_confirmation_uses_the_master_reference_key(tmp_path, reference, from_excel):
    app = create_app(local_settings(tmp_path / "manual-reference.db"))
    with local_client(app) as client:
        shipment = create(client, reference_raw=reference)
        environment = {"client": client, "headers": lambda role: {}, "supplier_id": LOCAL_SUPPLIER}
        provision(environment, shipment)
        if from_excel:
            content = workbook(rows=[[
                "MXG", "Example Test Carrier", "FREIGHT", reference, "KEY-001",
                "10/10/2026", "OCTUBRE", "USD", "500", "500", "500", "0", "SEA IMPO",
            ]])
            data = payload(content, create_suppliers=False)
            # The local supplier's name differs from the synthetic workbook fixture.
            data["supplier_map"] = {"EXAMPLE TEST CARRIER": str(LOCAL_SUPPLIER)}
            preview = client.post("/api/v1/finance/import/preview", json=data)
            assert preview.status_code == 200, preview.text
            assert preview.json()["counts"]["READY"] == 1
            data["selected"] = [preview.json()["groups"][0]["key"]]
            result = client.post("/api/v1/finance/import/confirm", json=data)
            assert result.status_code == 201, result.text
            invoice_id = result.json()["invoices"][0]["id"]
            result = client.get("/api/v1/finance/invoices?month=2026-10-01")
            assert result.status_code == 200, result.text
            row = next(item for item in result.json()["items"] if item["id"] == invoice_id)
        else:
            row = invoice(environment, shipment, company_code="MXG", number="KEY-001")
        assert Decimal(row["applied_amount"]) == 500
        assert Decimal(row["pending_amount"]) == 0
        with app.state.session_factory() as session:
            identifier = session.scalar(select(InvoiceLineIdentifier))
            assert identifier.raw_value == reference
            assert identifier.normalized_value == normalize_reference(reference)
            assert identifier.normalization_version == VERSION
