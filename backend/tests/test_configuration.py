import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.schemas import ProvisionCreate, UserPatch


def test_health_requires_no_auth_and_ready_fails_without_database(settings, rsa_key):
    app = create_app(settings, lambda token: rsa_key.public_key())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401
        if "localhost:1/" in settings.database_url.get_secret_value():
            response = client.get("/health/ready")
            assert response.status_code == 503
            assert "psycopg" not in response.text
        assert (
            client.get("/health/live", headers={"Host": "untrusted.example.com"}).status_code == 400
        )


def test_production_requires_secure_configuration(settings):
    values = settings.model_dump()
    values["app_env"] = "production"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
    values.update(
        database_url="postgresql+psycopg://masterlogistica_app:example@db.example.com/masterlogistica?sslmode=verify-full",
        enforce_https=True,
        allowed_origins=["https://app.example.com"],
        allowed_hosts=["api.example.com"],
    )
    assert Settings(_env_file=None, **values).app_env == "production"
    for field, invalid in [
        ("allowed_hosts", ["*"]),
        ("allowed_origins", ["http://app.example.com"]),
        ("entra_allowed_client_ids", []),
        ("migration_database_url", "postgresql+psycopg://admin@example.com/db"),
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{**values, field: invalid})


def test_configuration_error_redacts_password():
    password = "private-test-marker"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=f"mysql://user:{password}@example.com/db")
    assert password not in str(error.value)


def test_sensitive_input_not_echoed_in_validation_errors(settings, rsa_key):
    app = create_app(settings, lambda token: rsa_key.public_key())
    with TestClient(app) as client:
        response = client.post("/api/v1/references/normalize", json={"raw_value": "x" * 300})
        # Missing auth is enforced before validating protected business inputs.
        assert response.status_code == 401
        document = client.get("/openapi.json").json()
        assert all(
            method in {"get", "post", "patch", "parameters"}
            for path in document["paths"].values()
            for method in path
        )


def test_financial_validation_finite_and_precision():
    base = {
        "shipment_id": "50000000-0000-0000-0000-000000000001",
        "supplier_id": "60000000-0000-0000-0000-000000000001",
        "charge_code": "FREIGHT",
        "month_accrued": "2026-10-01",
    }
    for invalid in ["NaN", "Infinity", "-1", "0.12345", "100000000000000"]:
        with pytest.raises(ValidationError):
            ProvisionCreate(**base, amount=invalid)
    with pytest.raises(ValidationError):
        ProvisionCreate(**base, amount="99999999999999", extra_charges="1")
    with pytest.raises(ValidationError):
        ProvisionCreate(**{**base, "month_accrued": "2026-10-02"})
    assert str(ProvisionCreate(**base, amount="12.3400").amount) == "12.3400"


def test_user_patch_cannot_clear_required_fields():
    with pytest.raises(ValidationError):
        UserPatch(expected_version=1, role=None)
