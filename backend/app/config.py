from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    entra_tenant_id: UUID | None = None
    entra_api_client_id: UUID | None = None
    entra_frontend_client_id: UUID | None = None
    entra_allowed_client_ids: list[UUID] = Field(default_factory=list)
    entra_required_scope: str = "access_as_user"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4200"])
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    company_codes: list[str] = Field(default_factory=lambda: ["JE_MX"])
    enforce_https: bool = False
    jwt_leeway_seconds: int = Field(default=30, ge=0, le=120)

    @field_validator(
        "entra_tenant_id", "entra_api_client_id", "entra_frontend_client_id", mode="before"
    )
    @classmethod
    def blank_identifier(cls, value):
        return None if value == "" else value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def postgres_only(cls, value):
        if value is not None:
            try:
                url = make_url(value.get_secret_value())
            except Exception:
                raise ValueError("Database URL must be a valid PostgreSQL URL") from None
            if url.drivername != "postgresql+psycopg":
                raise ValueError("Use the postgresql+psycopg database driver")
        return value

    @field_validator("company_codes")
    @classmethod
    def valid_company_codes(cls, values):
        if not values or any(not v.strip() or len(v) > 32 for v in values):
            raise ValueError("Configure at least one company code, up to 32 characters")
        return values

    @model_validator(mode="after")
    def production_controls(self):
        if self.app_env == "production":
            if not self.entra_configured or not self.entra_allowed_client_ids:
                raise ValueError("Production requires Entra tenant, API and allowed client IDs")
            if not self.enforce_https:
                raise ValueError("Production requires HTTPS enforcement")
            if not self.allowed_hosts or "*" in self.allowed_hosts:
                raise ValueError("Production requires explicit allowed hosts")
            if any(not origin.startswith("https://") for origin in self.allowed_origins):
                raise ValueError("Production CORS origins must use HTTPS")
            url = make_url(self.database_url.get_secret_value())
            if url.username != "masterlogistica_app":
                raise ValueError("Production API must use the restricted database role")
            if url.query.get("sslmode") != "verify-full":
                raise ValueError("Production PostgreSQL connections require sslmode=verify-full")
            if self.migration_database_url is not None:
                raise ValueError("Do not provide migration credentials to the production API")
        return self

    @property
    def entra_configured(self) -> bool:
        return self.entra_tenant_id is not None and self.entra_api_client_id is not None

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}"

    @property
    def issuer(self) -> str:
        return f"{self.authority}/v2.0"

    @property
    def jwks_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}/discovery/v2.0/keys"


class MigrationSettings(BaseSettings):
    """Database-only settings for a separate migration/bootstrap job, including production."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )
    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    entra_tenant_id: UUID | None = None

    @field_validator("entra_tenant_id", mode="before")
    @classmethod
    def blank_identifier(cls, value):
        return None if value == "" else value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def postgres_only(cls, value):
        return Settings.postgres_only(value)

    @model_validator(mode="after")
    def restricted_job(self):
        url = make_url((self.migration_database_url or self.database_url).get_secret_value())
        if url.username == "masterlogistica_app":
            raise ValueError("Migrations require the separate migration database role")
        if self.app_env == "production" and url.query.get("sslmode") != "verify-full":
            raise ValueError("Production migrations require sslmode=verify-full")
        return self
