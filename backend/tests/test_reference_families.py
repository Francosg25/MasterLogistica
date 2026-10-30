"""Official numbered movements, stable families, scoped access and separate financial ledgers."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.main import create_app
from app.references import normalize_reference, parse_reference
from tests.test_finance import api, invoice, provision
from tests.test_integration import create_shipment
from tests.test_local import local_client, local_settings
from tests.test_local import local_financial_environment as local_financial_environment


def movement(e, root, **changes):
    values = {
        k: root[k]
        for k in (
            "company_code",
            "process_code",
            "operation_code",
            "reference_year",
            "business_unit",
            "department_code",
        )
    }
    response = e["client"].post(
        "/api/v1/shipments",
        headers=e["headers"]("admin"),
        json={**values, "parent_shipment_id": root["id"], **changes},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("suffix", [".1", ".2", ".15", ".1.DMR", ".2.PFA", ".3.CS1280"])
def test_numeric_movements_keep_their_unique_identity(suffix):
    raw = "RM8-1616VI26-M23-MAT" + suffix
    parsed = parse_reference(raw)
    assert parsed.family_base == "RM8-1616VI26-M23-MAT"
    assert parsed.movement_number == int(suffix.split(".")[1])
    assert normalize_reference(raw) == raw
    assert normalize_reference(raw) != normalize_reference(parsed.family_base)


def test_children_are_sequential_keep_root_identity_and_financial_balances_separate(
    local_financial_environment,
):
    e = local_financial_environment
    root = create_shipment(e)
    one, two = movement(e, root), movement(e, root)
    assert one["reference_raw"] == root["reference_raw"] + ".1"
    assert two["reference_raw"] == root["reference_raw"] + ".2"
    assert one["parent_shipment_id"] == root["id"]
    provision(e, root, amount="500")
    provision(e, one, amount="300")
    invoice(e, one, amount="300")
    balances = api(e, "get", "/balances?month=2026-10-01")["items"]
    assert {b["reference"]: b["status"] for b in balances} == {
        root["reference_raw"]: "OPEN",
        one["reference_raw"]: "CLOSED",
    }
    family = (
        e["client"]
        .get(f"/api/v1/shipments/{one['id']}/family", headers=e["headers"]("admin"))
        .json()
    )
    assert family["root"]["id"] == root["id"] and len(family["members"]) == 3
    # Renaming the root never detaches already linked movements.
    changed = e["client"].patch(
        f"/api/v1/shipments/{root['id']}",
        headers=e["headers"]("one"),
        json={"expected_version": root["row_version"], "reference_raw": "REFERENCE-RENAMED"},
    )
    assert changed.status_code == 200
    assert (
        e["client"]
        .get(f"/api/v1/shipments/{one['id']}/family", headers=e["headers"]("admin"))
        .json()["root"]["reference_raw"]
        == "REFERENCE-RENAMED"
    )


def test_parallel_movements_reserve_existing_numeric_aliases(local_financial_environment):
    e = local_financial_environment
    root = create_shipment(e)
    create_shipment(e, reference_raw=root["reference_raw"] + ".4")
    with ThreadPoolExecutor(max_workers=3) as pool:
        children = list(pool.map(lambda _: movement(e, root), range(3)))
    assert sorted(c["movement_number"] for c in children) == [5, 6, 7]
    assert len({c["reference_raw"] for c in children}) == 3


def test_family_and_creation_enforce_scope_and_root_classification(local_financial_environment):
    e = local_financial_environment
    root = create_shipment(e)
    child = movement(e, root)
    assert (
        e["client"]
        .get(f"/api/v1/shipments/{child['id']}/family", headers=e["headers"]("two"))
        .status_code
        == 404
    )
    values = {
        k: root[k]
        for k in (
            "company_code",
            "process_code",
            "operation_code",
            "reference_year",
            "business_unit",
            "department_code",
        )
    }
    for changes in (
        {"business_unit": "M45"},
        {"reference_raw": "MANUAL-CHILD"},
        {"parent_shipment_id": child["id"]},
    ):
        response = e["client"].post(
            "/api/v1/shipments",
            headers=e["headers"]("admin"),
            json={**values, "parent_shipment_id": root["id"], **changes},
        )
        assert response.status_code == 422
    response = e["client"].post(
        "/api/v1/shipments",
        headers=e["headers"]("two"),
        json={**values, "parent_shipment_id": root["id"]},
    )
    assert response.status_code == 404
    changed = e["client"].patch(
        f"/api/v1/shipments/{child['id']}",
        headers=e["headers"]("admin"),
        json={"expected_version": 1, "company_code": "MXT"},
    )
    assert changed.status_code == 422


def test_overview_is_scoped_and_separates_currency_totals(local_financial_environment):
    e = local_financial_environment
    own = create_shipment(e)
    other = create_shipment(e, "two")
    provision(e, own, amount="500", currency="USD")
    provision(e, other, amount="700", currency="MXN")
    own_view = (
        e["client"]
        .get("/api/v1/workspace/overview?month=2026-10-01", headers=e["headers"]("one"))
        .json()
    )
    assert own_view["active_references"] == 1 and own_view["live_provisions"] == 1
    assert [t["currency"] for t in own_view["totals"]] == ["USD"]
    all_view = (
        e["client"]
        .get("/api/v1/workspace/overview?month=2026-10-01", headers=e["headers"]("admin"))
        .json()
    )
    assert len(all_view["totals"]) == 2 and len(all_view["recent"]) == 2
    assert (
        e["client"]
        .get("/api/v1/workspace/overview?month=2026-10-15", headers=e["headers"]("one"))
        .status_code
        == 422
    )


def test_version_six_upgrade_is_additive_and_keeps_existing_ids(tmp_path):
    settings = local_settings(tmp_path / "upgrade.db")
    first = create_app(settings)
    with local_client(first) as client:
        root = client.post(
            "/api/v1/shipments",
            json={
                "company_code": "LOCAL",
                "process_code": "RM",
                "operation_code": "VI",
                "reference_year": 2026,
                "business_unit": "M00",
            },
        ).json()
    with first.state.engine.begin() as connection:
        # Simulate the actual previous schema, including removal of the new unique constraint.
        connection.exec_driver_sql("UPDATE local_schema_version SET version=6")
    with local_client(create_app(settings)) as client:
        stored = client.get(f"/api/v1/shipments/{root['id']}").json()
        assert stored == root
        assert client.get("/health/ready").status_code == 200
        catalog = client.get("/api/v1/references/catalogs").json()
        assert set(catalog["business_units"]) == {
            "M00",
            "M01",
            "M19",
            "M20",
            "M23",
            "M45",
            "M46",
            "M65",
        }
        owners = client.get("/api/v1/masters/owners").json()
        assert [o["analyst_code"] for o in owners] == list(range(1, 9))
        assert all(o["layout_code"] == "COMPLIANCE" for o in owners if o["analyst_code"] > 5)


def test_legacy_child_spelling_keeps_its_financial_key_and_reserves_the_number(
    local_financial_environment,
):
    e = local_financial_environment
    root = create_shipment(e)
    # The earlier parser treated numeric suffixes literally, including their zeros.
    short = root["reference_raw"].replace("-0001", "-1") + ".7"
    assert normalize_reference(short) == short
    child = create_shipment(e, reference_raw=short)
    family = (
        e["client"]
        .get(f"/api/v1/shipments/{child['id']}/family", headers=e["headers"]("admin"))
        .json()
    )
    assert family["root"]["id"] == root["id"]
    assert any(m["id"] == child["id"] for m in family["members"])
    following = movement(e, root)
    assert following["movement_number"] == 8


def test_actual_previous_sqlite_columns_upgrade_without_rewriting_references(tmp_path):
    from app.local_schema import local_metadata

    settings = local_settings(tmp_path / "old-schema.db")
    app = create_app(settings)
    metadata = local_metadata()
    shipments = metadata.tables["shipments"]
    for constraint in list(shipments.constraints):
        if constraint.name in {"uq_shipment_movement", "ck_shipment_parent"} or any(
            c.name == "parent_shipment_id" for c in getattr(constraint, "columns", [])
        ):
            shipments.constraints.discard(constraint)
    shipments._columns.remove(shipments.c.parent_shipment_id)
    shipments._columns.remove(shipments.c.movement_number)
    with app.state.engine.begin() as connection:
        metadata.create_all(connection)
        connection.exec_driver_sql("CREATE TABLE local_schema_version(version INTEGER NOT NULL)")
        connection.exec_driver_sql("INSERT INTO local_schema_version VALUES (6)")
    with local_client(app) as client:
        created = client.post(
            "/api/v1/shipments",
            json={
                "company_code": "MXG",
                "process_code": "RM",
                "operation_code": "SI",
                "reference_year": 2026,
                "business_unit": "M65",
            },
        )
        assert created.status_code == 201, created.text
        root = created.json()
        child = client.post(
            "/api/v1/shipments",
            json={
                "parent_shipment_id": root["id"],
                "company_code": "MXG",
                "process_code": "RM",
                "operation_code": "SI",
                "reference_year": 2026,
                "business_unit": "M65",
            },
        )
        assert child.status_code == 201, child.text
        assert child.json()["movement_number"] == 1
