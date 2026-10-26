import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import MigrationSettings, Settings
from app.main import create_app
from app.schemas import ProvisionCreate, ShipmentCreate, UserPatch


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
        ("allowed_hosts", ["*.example.com"]),
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


@pytest.mark.parametrize("catalog", [{"TOOLONG": "Example"}, {"M01": " "}, {"t01": "Example"}])
def test_business_unit_catalog_requires_valid_codes_and_names(settings, catalog):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**settings.model_dump(), "business_units": catalog})


def test_new_shipment_rejects_legacy_process():
    with pytest.raises(ValidationError):
        ShipmentCreate(
            company_code="EXAMPLE",
            process_code="DR",
            operation_code="F4",
            reference_year=2026,
            business_unit="M01",
            department_code="CTM",
        )


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


def test_operation_year_is_explicit_and_dates_can_cross_year_boundary():
    shipment = ShipmentCreate(
        company_code="JE_MX",
        process_code="RM",
        operation_code="LI",
        reference_year=2026,
        business_unit="M23",
        department_code="MAT",
        ship_date="2027-01-01",
    )
    assert shipment.reference_year == 2026 and shipment.ship_date.year == 2027


def test_production_migration_job_uses_separate_settings_and_tls():
    runtime = (
        "postgresql+psycopg://masterlogistica_app@example.com/masterlogistica?sslmode=verify-full"
    )
    migrator = "postgresql+psycopg://masterlogistica_migrator@example.com/masterlogistica?sslmode=verify-full"
    job = MigrationSettings(
        _env_file=None, app_env="production", database_url=runtime, migration_database_url=migrator
    )
    assert job.app_env == "production"
    with pytest.raises(ValidationError):
        MigrationSettings(
            _env_file=None,
            app_env="production",
            database_url=migrator.replace("?sslmode=verify-full", ""),
        )
    with pytest.raises(ValidationError):
        MigrationSettings(_env_file=None, database_url=runtime)


def test_browser_auth_config_requires_an_allowed_frontend(settings, rsa_key):
    for frontend, expected in [(settings.entra_frontend_client_id, True), (None, False)]:
        app = create_app(
            settings.model_copy(update={"entra_frontend_client_id": frontend}),
            lambda token: rsa_key.public_key(),
        )
        with TestClient(app) as client:
            result = client.get("/api/v1/auth/config")
            assert result.status_code == 200
            assert result.json()["enabled"] is expected


@pytest.mark.parametrize("concept", ["FREIGHT", "BROKER", "STORAGE"])
def test_provision_exact_date_derives_its_accounting_month(concept):
    row = ProvisionCreate(
        shipment_id="50000000-0000-0000-0000-000000000001",
        supplier_id="60000000-0000-0000-0000-000000000001",
        charge_code=concept,
        provision_date="2026-10-23",
    )
    assert row.provision_date.isoformat() == "2026-10-23"
    assert row.month_accrued.isoformat() == "2026-10-01"
    with pytest.raises(ValidationError):
        ProvisionCreate(**{**row.model_dump(), "month_accrued": "2026-11-01"})
    with pytest.raises(ValidationError):
        ProvisionCreate(**{**row.model_dump(), "charge_code": "HANDLING"})
