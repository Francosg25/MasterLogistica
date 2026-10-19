"""Master query contract and role checks without an external identity provider or database."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import current_user
from app.db import get_session
from app.main import create_app


class EmptySession:
    def __init__(self):
        self.queries = []

    def scalar(self, statement):
        self.queries.append(statement)
        return 0

    def scalars(self, statement):
        self.queries.append(statement)
        return SimpleNamespace(all=lambda: [])

    def execute(self, statement):
        self.queries.append(statement)
        return SimpleNamespace(all=lambda: [])


@pytest.fixture
def scoped_client(settings, rsa_key):
    actor = SimpleNamespace(id=uuid4(), role="OPERATOR")
    db = EmptySession()
    app = create_app(settings, lambda token: rsa_key.public_key())
    app.dependency_overrides[current_user] = lambda: actor
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        yield client, actor, db


@pytest.mark.parametrize("path", ["/masters/shipments", "/masters/summary"])
def test_master_requires_operation(scoped_client, path):
    client, actor, db = scoped_client
    params = {"owner_id": str(actor.id), "operation_code": "SI"}
    params.pop("operation_code")
    assert client.get("/api/v1" + path, params=params).status_code == 422
    assert db.queries == []


@pytest.mark.parametrize("role", ["OPERATOR", "FINANCE", "MANAGER", "SUPER_ADMIN"])
def test_ownerless_master_retains_role_scope(scoped_client, role):
    client, actor, db = scoped_client
    actor.role = role
    assert (
        client.get("/api/v1/masters/shipments", params={"operation_code": "SI"}).status_code == 200
    )
    for statement in db.queries:
        compiled = statement.compile()
        assert "SI" in compiled.params.values()
        assert (actor.id in compiled.params.values()) == (role in {"OPERATOR", "FINANCE"})


@pytest.mark.parametrize("role", ["OPERATOR", "FINANCE"])
@pytest.mark.parametrize("path", ["/masters/shipments", "/masters/summary"])
def test_nonconsolidated_role_cannot_select_another_owner(scoped_client, path, role):
    client, actor, db = scoped_client
    actor.role = role
    response = client.get(
        "/api/v1" + path, params={"owner_id": str(uuid4()), "operation_code": "SI"}
    )
    assert response.status_code == 403
    assert db.queries == []


@pytest.mark.parametrize("role", ["OPERATOR", "MANAGER", "SUPER_ADMIN", "FINANCE"])
@pytest.mark.parametrize("path", ["/masters/shipments", "/masters/summary"])
def test_master_queries_keep_explicit_owner_and_operation(scoped_client, path, role):
    client, actor, db = scoped_client
    actor.role = role
    owner = uuid4() if role in {"MANAGER", "SUPER_ADMIN"} else actor.id
    response = client.get("/api/v1" + path, params={"owner_id": str(owner), "operation_code": "SI"})
    assert response.status_code == 200
    assert db.queries
    for statement in db.queries:
        compiled = statement.compile()
        assert owner in compiled.params.values()
        assert "SI" in compiled.params.values()
        assert "shipments.owner_id =" in str(compiled)
        assert "shipments.operation_code =" in str(compiled)


@pytest.mark.parametrize("operation", ["", "ALL", "SI,AI", "INVALID"])
def test_master_rejects_combined_or_unknown_operations(scoped_client, operation):
    client, actor, db = scoped_client
    assert (
        client.get(
            "/api/v1/masters/shipments",
            params={"owner_id": str(actor.id), "operation_code": operation},
        ).status_code
        == 422
    )
    assert db.queries == []


@pytest.mark.parametrize("role", ["FINANCE", "MANAGER"])
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/shipments"),
        ("PATCH", "/shipments/00000000-0000-0000-0000-000000000001"),
        ("POST", "/shipments/00000000-0000-0000-0000-000000000001/identifiers"),
    ],
)
def test_readonly_operational_roles_cannot_write_through_api(scoped_client, role, method, path):
    client, actor, db = scoped_client
    actor.role = role
    assert client.request(method, "/api/v1" + path, json={}).status_code == 403
    assert db.queries == []
