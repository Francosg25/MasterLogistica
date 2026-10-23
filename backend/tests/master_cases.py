"""Manual master capture contract shared by SQLite and PostgreSQL tests."""

from decimal import Decimal

from tests import test_finance as finance
from tests.test_integration import create_shipment


def assert_manual_master_capture(e):
    row = create_shipment(
        e,
        operation_code="SEA IMPO",
        status="On Water-Loaded",
        carrier_broker_name="Transportista manual de prueba",
    )
    assert row["operation_code"] == "SEA IMPO"
    assert row["status"] == "On Water-Loaded"
    assert "SI26" in row["reference_raw"]
    assert row["transport_mode"] == "SEA" and row["direction"] == "I"
    assert row["carrier_broker_id"] is None
    provision = finance.provision(e, row)
    path = "/api/v1/shipments/" + row["id"]
    changes = dict(
        operation_code="Transporte especial / terrestre",
        status="Outgated for Transload",
        carrier_broker_name="Agente temporal de prueba",
        shipping_line_name="Naviera manual de prueba",
    )
    updated = e["client"].patch(
        path, headers=e["headers"]("one"), json={"expected_version": row["row_version"], **changes}
    )
    assert updated.status_code == 200, updated.text
    updated = updated.json()
    assert updated["id"] == row["id"] and updated["reference_raw"] == row["reference_raw"]
    assert all(updated[key] == value for key, value in changes.items())
    assert updated["carrier_broker_id"] is updated["shipping_line_id"] is None
    assert e["client"].get(path, headers=e["headers"]("one")).json() == updated
    catalog = e["client"].get("/api/v1/references/catalogs", headers=e["headers"]("one")).json()
    assert changes["operation_code"] in catalog["operation_codes"]
    assert changes["status"] in catalog["shipment_statuses"]
    rows = (
        e["client"]
        .get(
            "/api/v1/masters/shipments",
            headers=e["headers"]("one"),
            params={"operation_code": changes["operation_code"]},
        )
        .json()
    )
    assert [item["id"] for item in rows["items"]] == [row["id"]]
    balance = finance.balances(e)["items"][0]
    assert balance["id"] == provision["id"] and Decimal(balance["closing_amount"]) == 500
    linked = e["client"].patch(
        path,
        headers=e["headers"]("one"),
        json={
            "expected_version": updated["row_version"],
            "carrier_broker_id": str(e["supplier_id"]),
        },
    )
    assert linked.status_code == 200, linked.text
    linked = linked.json()
    assert (
        linked["carrier_broker_id"] == str(e["supplier_id"])
        and linked["carrier_broker_name"] is None
    )
    assert linked["shipping_line_name"] == changes["shipping_line_name"]
    cleared = e["client"].patch(
        path,
        headers=e["headers"]("one"),
        json={
            "expected_version": linked["row_version"],
            "operation_code": None,
            "status": "",
            "shipping_line_name": None,
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["operation_code"] is None and cleared.json()["status"] == ""
    history = finance.api(e, "get", "/history")
    assert any(
        change["field"] == "operation_code" and change["after"] == changes["operation_code"]
        for event in history["items"]
        for change in event["changes"]
    )

    manual = create_shipment(
        e,
        operation_code="Captura manual mixta",
        status="Recolectado",
        shipping_line_name="Naviera adicional de prueba",
    )
    assert manual["operation_code"] == "Captura manual mixta"
    assert manual["status"] == "Recolectado"
    assert manual["id"] != row["id"] and manual["reference_raw"] != row["reference_raw"]
    assert manual["shipping_line_name"] == "Naviera adicional de prueba"
