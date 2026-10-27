"""SEC is assigned once per record; choice columns persist valid catalog values."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import select

from app.local_schema import SCHEMA_VERSION
from app.main import create_app
from app.models import ReferenceCounter, Shipment
from tests.test_local import local_client
from tests.test_master_layouts import BASE, create, patch
from tests.test_master_layouts import local_master as local_master


def test_sec_is_sequential_for_manual_and_automatic_references_in_each_master(local_master):
    settings, _, client = local_master
    owners = client.get("/api/v1/masters/owners").json()
    for owner in owners:
        first = create(client, owner_id=owner["id"], reference_raw=f"MANUAL-{owner['layout_code']}")
        assert first["master_data"]["sec"] == "1"
        assert first["reference_sequence"] == 1
        second = create(client, owner_id=owner["id"])
        assert second["master_data"]["sec"] == "2"
        assert second["reference_raw"].startswith(f"RM{owner['analyst_code']}-0002")
        edited = patch(client, first, reference_raw=f"CORREGIDA-{owner['layout_code']}")
        assert edited["master_data"]["sec"] == "1"
        assert create(client, owner_id=owner["id"])["master_data"]["sec"] == "3"
    with local_client(create_app(settings)) as restarted:
        for owner in owners:
            assert create(restarted, owner_id=owner["id"])["master_data"]["sec"] == "4"


def test_failed_captures_do_not_consume_sec_and_clients_cannot_replace_it(local_master):
    _, _, client = local_master
    first = create(client, reference_raw="MANUAL-UNICA")
    duplicate = client.post("/api/v1/shipments", json={**BASE, "reference_raw": "MANUAL-UNICA"})
    assert duplicate.status_code == 422
    for value in ("20", None, ""):
        result = client.patch(
            "/api/v1/shipments/" + first["id"],
            json={"expected_version": 1, "origin": "No guardar", "master_data": {"sec": value}},
        )
        assert result.status_code == 422
        assert "automáticamente" in result.text
    assert client.get("/api/v1/shipments/" + first["id"]).json() == first
    assert create(client)["master_data"]["sec"] == "2"


def test_concurrent_captures_allocate_distinct_sec_without_skipping(local_master):
    _, _, client = local_master
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(lambda _: create(client), range(5)))
    assert sorted(int(row["master_data"]["sec"]) for row in rows) == [1, 2, 3, 4, 5]
    assert len({row["reference_normalized"] for row in rows}) == 5


@pytest.mark.parametrize("key,valid,bad", [("currency", "mxn", "EUR"), ("io", "i", "N")])
def test_choice_columns_are_normalized_and_invalid_pastes_are_atomic(local_master, key, valid, bad):
    _, _, client = local_master
    row = create(client, master_data={key: valid})
    assert row["master_data"][key] == valid.upper()
    response = client.patch(
        "/api/v1/shipments/" + row["id"],
        json={"expected_version": 1, "sender": "No guardar", "master_data": {key: bad}},
    )
    assert response.status_code == 422
    assert client.get("/api/v1/shipments/" + row["id"]).json() == row
    row = patch(client, row, master_data={key: None})
    assert row["master_data"][key] is None


def test_upgrade_fills_only_missing_sec_and_continues_historical_numbers(local_master):
    settings, app, client = local_master
    first = create(client)
    missing = create(client, reference_raw="ANTERIOR-SIN-SEC")
    captured = create(client, reference_raw="ANTERIOR-CON-SEC")
    with app.state.session_factory() as session, session.begin():
        session.get(Shipment, UUID(first["id"])).master_data = {"owner": "Conservar"}
        session.get(Shipment, UUID(missing["id"])).master_data = {"pedimento": "Conservar"}
        session.get(Shipment, UUID(missing["id"])).reference_sequence = None
        session.get(Shipment, UUID(captured["id"])).master_data = {"sec": "60"}
        session.get(Shipment, UUID(captured["id"])).legacy_sec = "55"
    before = {
        row["id"]: client.get("/api/v1/shipments/" + row["id"]).json()
        for row in (first, missing, captured)
    }
    with app.state.engine.begin() as connection:
        audit = connection.exec_driver_sql("SELECT count(*) FROM reconciliation_logs").scalar_one()
        connection.exec_driver_sql("UPDATE local_schema_version SET version = 5")
    upgraded_app = create_app(settings)
    with local_client(upgraded_app) as restarted:
        for row, expected in ((first, "1"), (missing, "61"), (captured, "60")):
            stored = restarted.get("/api/v1/shipments/" + row["id"]).json()
            assert stored["master_data"]["sec"] == expected
            assert stored["reference_raw"] == before[row["id"]]["reference_raw"]
            assert stored["row_version"] == before[row["id"]]["row_version"] + (row is not captured)
        with upgraded_app.state.engine.begin() as connection:
            assert (
                connection.exec_driver_sql("SELECT version FROM local_schema_version").scalar_one()
                == SCHEMA_VERSION
            )
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM reconciliation_logs").scalar_one()
                == audit
            )
        assert create(restarted)["master_data"]["sec"] == "62"


def test_sec_keeps_counting_after_four_digits(local_master):
    _, app, client = local_master
    with app.state.session_factory() as session, session.begin():
        counter = session.scalar(select(ReferenceCounter).where(ReferenceCounter.last_value == 0))
        owner = str(counter.owner_id)
        counter.last_value = 9999
    row = create(client, owner_id=owner)
    assert row["master_data"]["sec"] == "10000"
    assert "-10000LI26-" in row["reference_raw"]
