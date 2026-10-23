from __future__ import annotations

import re
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from app.catalogs import BUSINESS_UNIT_CODES


def local_database_url():
    path = Path(__file__).resolve().parents[2] / ".data" / "masterlogistica.db"
    return SecretStr(
        URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = Field(default_factory=local_database_url)
    auth_mode: Literal["development", "entra"] | None = None
    migration_database_url: SecretStr | None = None
    entra_tenant_id: UUID | None = None
    entra_api_client_id: UUID | None = None
    entra_frontend_client_id: UUID | None = None
    entra_allowed_client_ids: list[UUID] = Field(default_factory=list)
    entra_required_scope: str = "access_as_user"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4200"])
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    company_codes: list[str] = Field(default_factory=lambda: ["JE_MX"])
    business_units: dict[str, str] = Field(
        default_factory=lambda: {code: code for code in BUSINESS_UNIT_CODES}
    )
    enforce_https: bool = False
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    entra_ca_bundle: str | None = None
    jwt_leeway_seconds: int = Field(default=30, ge=0, le=120)

    @field_validator(
        "entra_tenant_id", "entra_api_client_id", "entra_frontend_client_id", mode="before"
    )
    @classmethod
    def blank_identifier(cls, value):
        return None if value == "" else value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def supported_database(cls, value):
        if value is not None:
            try:
                url = make_url(value.get_secret_value())
            except Exception:
                raise ValueError("Database URL must be a valid database URL") from None
            if url.drivername not in {"postgresql+psycopg", "sqlite+pysqlite"}:
                raise ValueError("Use postgresql+psycopg or local sqlite+pysqlite")
        return value

    @field_validator("company_codes")
    @classmethod
    def valid_company_codes(cls, values):
        if not values or any(not v.strip() or len(v) > 32 for v in values):
            raise ValueError("Configure at least one company code, up to 32 characters")
        return values

    @field_validator("trusted_proxy_ips")
    @classmethod
    def explicit_proxy_addresses(cls, values):
        for value in values:
            try:
                address = ip_address(value)
            except ValueError:
                raise ValueError("Trusted proxies must be individual IP addresses") from None
            if address.is_unspecified or address.is_multicast:
                raise ValueError("Trusted proxies must be individual host addresses")
        return values

    @field_validator("business_units", mode="before")
    @classmethod
    def empty_business_units(cls, value):
        return {} if value is None else value

    @field_validator("business_units")
    @classmethod
    def approved_business_units(cls, values):
        if any(not re.fullmatch(r"[A-Z0-9]{3}", code, re.ASCII) for code in values):
            raise ValueError("Business unit codes must contain three uppercase letters or digits")
        if any(
            not description.strip() or len(description) > 250 for description in values.values()
        ):
            raise ValueError("Business unit descriptions must contain 1 to 250 characters")
        return {code: values.get(code, code).strip() for code in BUSINESS_UNIT_CODES}

    @model_validator(mode="after")
    def production_controls(self):
        url = make_url(self.database_url.get_secret_value())
        if self.auth_mode is None:
            self.auth_mode = "development" if url.drivername == "sqlite+pysqlite" else "entra"
        if self.auth_mode == "development":
            if self.app_env not in {"development", "test"} or url.drivername != "sqlite+pysqlite":
                raise ValueError("Development identity requires local SQLite outside production")
            if (
                url.host
                or url.username
                or url.password
                or url.query
                or not url.database
                or not Path(url.database).is_absolute()
            ):
                raise ValueError(
                    "Local SQLite requires an absolute file path without URL parameters"
                )
            if (
                self.migration_database_url is not None
                or self.trusted_proxy_ips
                or self.enforce_https
            ):
                raise ValueError(
                    "Local development cannot use migration credentials or a trusted proxy"
                )
            if not self.allowed_hosts or any(
                host not in {"localhost", "127.0.0.1", "::1", "[::1]"}
                for host in self.allowed_hosts
            ):
                raise ValueError("Local development hosts must be loopback only")
            if any(
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}
                or urlsplit(origin).path not in {"", "/"}
                or urlsplit(origin).query
                or urlsplit(origin).fragment
                or urlsplit(origin).username
                for origin in self.allowed_origins
            ):
                raise ValueError("Local development origins must use HTTP on loopback")
            if "allowed_origins" not in self.model_fields_set:
                self.allowed_origins = ["http://127.0.0.1:4200", "http://localhost:4200"]
            if "company_codes" not in self.model_fields_set:
                self.company_codes = ["LOCAL"]
        elif url.drivername != "postgresql+psycopg":
            raise ValueError("Corporate identity requires PostgreSQL; SQLite is development only")
        if self.app_env == "production":
            if self.auth_mode != "entra":
                raise ValueError("Production requires Entra authentication")
            if not self.entra_configured or not self.entra_allowed_client_ids:
                raise ValueError("Production requires Entra tenant, API and allowed client IDs")
            if self.entra_frontend_client_id not in self.entra_allowed_client_ids:
                raise ValueError("Production requires an explicitly allowed frontend client")
            if not self.business_units:
                raise ValueError("Production requires an approved business unit catalog")
            if not self.enforce_https:
                raise ValueError("Production requires HTTPS enforcement")
            if not self.allowed_hosts or any(
                not host or "*" in host for host in self.allowed_hosts
            ):
                raise ValueError("Production requires explicit allowed hosts")
            if not self.allowed_origins or any(
                urlsplit(origin).scheme != "https"
                or not urlsplit(origin).hostname
                or urlsplit(origin).path not in {"", "/"}
                or urlsplit(origin).query
                or urlsplit(origin).fragment
                or urlsplit(origin).username is not None
                for origin in self.allowed_origins
            ):
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
        if value is not None:
            try:
                url = make_url(value.get_secret_value())
            except Exception:
                raise ValueError("Invalid PostgreSQL migration URL") from None
            if url.drivername != "postgresql+psycopg":
                raise ValueError("Corporate migrations require PostgreSQL")
        return value

    @model_validator(mode="after")
    def restricted_job(self):
        url = make_url((self.migration_database_url or self.database_url).get_secret_value())
        if url.username == "masterlogistica_app":
            raise ValueError("Migrations require the separate migration database role")
        if self.app_env == "production" and url.query.get("sslmode") != "verify-full":
            raise ValueError("Production migrations require sslmode=verify-full")
        return self
