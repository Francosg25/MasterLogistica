import os
import time
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings

TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
API_ID = UUID("20000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("30000000-0000-0000-0000-000000000001")
OBJECT_ID = UUID("40000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://localhost:1/masterlogistica_test"
        ),
        entra_tenant_id=TENANT_ID,
        entra_api_client_id=API_ID,
        entra_frontend_client_id=CLIENT_ID,
        entra_allowed_client_ids=[CLIENT_ID],
        allowed_hosts=["testserver", "localhost", "127.0.0.1"],
        jwt_leeway_seconds=0,
    )


@pytest.fixture
def token_factory(settings, rsa_key):
    def build(object_id=OBJECT_ID, *, changes=None, algorithm="RS256", headers=None, key=None):
        now = int(time.time())
        claims = {
            "iss": settings.issuer,
            "aud": str(API_ID),
            "tid": str(TENANT_ID),
            "oid": str(object_id),
            "sub": "test-subject",
            "ver": "2.0",
            "scp": "access_as_user",
            "azp": str(CLIENT_ID),
            "iat": now - 1,
            "nbf": now - 1,
            "exp": now + 3600,
        }
        for name, value in (changes or {}).items():
            if value is None:
                claims.pop(name, None)
            else:
                claims[name] = value
        return jwt.encode(
            claims,
            key if key is not None else rsa_key,
            algorithm=algorithm,
            headers=headers or {"kid": "test-key"},
        )

    return build
