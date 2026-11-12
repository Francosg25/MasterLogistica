"""Fixed selection catalogs preserve historical records and normalize known operation aliases."""

from uuid import UUID

import pytest

from app.local_schema import LOCAL_TENANT, RETIRED_LOCAL_MASTERS
from app.main import create_app
from app.models import ReferenceCounter, Shipment, User
from app.references import OPERATIONS
from tests.test_local import local_client, local_settings


def create(client, **values):
    response = client.post(
        "/api/v1/shipments",
        json={
            "company_code": "MXG",
            "process_code": "RM",
            "operation_code": "SI",
            "reference_year": 2026,
            "business_unit": "M01",
            **values,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_historical_values_do_not_expand_selection_catalogs(tmp_path):
    app = create_app(local_settings(tmp_path / "catalogs.db", company_codes=["LOCAL", "O"]))
    with local_client(app) as client:
        air = create(client, company_code="LOCAL", operation_code="AIR IMPO")
        sea = create(client, company_code="O", operation_code="SEA IMPO")
        unknown = create(client, operation_code="FDSG", reference_raw="LEGACY-UNKNOWN-OPERATION")
        assert air["operation_code"] == "AI"
        assert sea["operation_code"] == "SI"
        # Older stored labels remain readable and must match the canonical filters.
        with app.state.session_factory() as session, session.begin():
            session.get(Shipment, UUID(air["id"])).operation_code = "AIR IMPO"
            session.get(Shipment, UUID(sea["id"])).operation_code = "SEA IMPO"
        catalog = client.get("/api/v1/references/catalogs").json()
        assert catalog["company_codes"] == ["MXG", "MXT"]
        assert set(catalog["operation_codes"]) == set(OPERATIONS)
        for operation, row in [("AI", air), ("SI", sea)]:
            listed = client.get(
                "/api/v1/masters/shipments", params={"operation_code": operation}
            ).json()
            assert listed["total"] == 1
            assert listed["items"][0]["id"] == row["id"]
            assert listed["items"][0]["operation_code"] == operation
            summary = client.get(
                "/api/v1/masters/summary", params={"operation_code": operation}
            ).json()
            assert summary["total"] == 1
        assert client.get("/api/v1/shipments/" + unknown["id"]).json()["operation_code"] == "FDSG"
        with app.state.session_factory() as session:
            assert session.get(Shipment, UUID(air["id"])).operation_code == "AIR IMPO"
            assert session.get(Shipment, UUID(air["id"])).company_code == "LOCAL"


@pytest.mark.parametrize("owner_id,name,code", RETIRED_LOCAL_MASTERS)
def test_old_local_compliance_presets_retire_without_deleting_their_records(
    tmp_path, owner_id, name, code
):
    settings = local_settings(tmp_path / "retired.db")
    app = create_app(settings)
    with local_client(app) as client:
        assert len(client.get("/api/v1/masters/owners").json()) == 5
        with app.state.session_factory() as session, session.begin():
            session.add(
                User(
                    id=owner_id,
                    entra_tenant_id=LOCAL_TENANT,
                    entra_object_id=owner_id,
                    email="old-compliance@example.invalid",
                    display_name=name,
                    role="OPERATOR",
                    analyst_code=code,
                )
            )
            session.flush()
            session.add(ReferenceCounter(owner_id=owner_id, last_value=0))
        historical = create(
            client, owner_id=str(owner_id), reference_raw="OLD-COMPLIANCE-REFERENCE"
        )
    restored = create_app(settings)
    with local_client(restored) as client:
        owners = client.get("/api/v1/masters/owners").json()
        assert [owner["analyst_code"] for owner in owners] == [1, 2, 3, 4, 5]
        assert len(client.get("/api/v1/finance/owners").json()) == 5
        assert client.get("/api/v1/shipments/" + historical["id"]).json()["id"] == historical["id"]
        with restored.state.session_factory() as session:
            assert session.get(User, owner_id).is_active is False
            assert session.get(ReferenceCounter, owner_id) is not None
