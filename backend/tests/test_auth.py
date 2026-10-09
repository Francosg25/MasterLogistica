import time

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.auth import EntraTokenValidator
from tests.conftest import OBJECT_ID, TENANT_ID


def test_valid_delegated_identity(settings, token_factory, rsa_key):
    validator = EntraTokenValidator(settings, lambda token: rsa_key.public_key())
    identity = validator.validate(token_factory())
    assert identity.tenant_id == TENANT_ID
    assert identity.object_id == OBJECT_ID


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://untrusted.example.com/v2.0"},
        {"aud": "wrong-api"},
        {"aud": ["20000000-0000-0000-0000-000000000001"]},
        {"tid": "10000000-0000-0000-0000-000000000002"},
        {"tid": 123},
        {"oid": "invalid-uuid"},
        {"oid": None},
        {"azp": "invalid-uuid"},
        {"azp": "30000000-0000-0000-0000-000000000002"},
        {"ver": "1.0"},
        {"scp": "other_scope"},
        {"scp": None},
        {"scp": ["access_as_user"]},
        {"exp": int(time.time()) - 3600},
        {"nbf": int(time.time()) + 3600},
        {"iat": int(time.time()) + 3600},
        {"exp": None},
        {"nbf": None},
        {"iat": None},
        {"sub": None},
    ],
)
def test_invalid_claims_rejected(settings, token_factory, rsa_key, changes):
    validator = EntraTokenValidator(settings, lambda token: rsa_key.public_key())
    with pytest.raises(HTTPException) as error:
        validator.validate(token_factory(changes=changes))
    assert error.value.status_code == 401
    assert error.value.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("token", ["", "broken.token.data", "x" * 16385])
def test_malformed_tokens(settings, rsa_key, token):
    with pytest.raises(HTTPException) as error:
        EntraTokenValidator(settings, lambda value: rsa_key.public_key()).validate(token)
    assert error.value.status_code == 401


def test_hmac_and_unsigned_tokens_rejected_before_key_fetch(settings, token_factory):
    def never_resolve(token):
        pytest.fail("Do not fetch keys for an unsupported algorithm")

    validator = EntraTokenValidator(settings, never_resolve)
    for algorithm, key in [("HS256", "test-only-symmetric-key-32-characters"), ("none", "")]:
        token = token_factory(algorithm=algorithm, key=key)
        with pytest.raises(HTTPException) as error:
            validator.validate(token)
        assert error.value.status_code == 401


def test_invalid_signature(settings, token_factory, rsa_key):
    another_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        EntraTokenValidator(settings, lambda token: another_key.public_key()).validate(
            token_factory()
        )
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "failure,status",
    [(PyJWKClientConnectionError("offline"), 503), (PyJWKClientError("unknown kid"), 401)],
)
def test_jwks_failures_fail_closed(settings, token_factory, failure, status):
    def resolve(token):
        raise failure

    with pytest.raises(HTTPException) as error:
        EntraTokenValidator(settings, resolve).validate(token_factory())
    assert error.value.status_code == status


def test_missing_configuration_has_no_dev_login_bypass(settings, token_factory, rsa_key):
    s = settings.model_copy(update={"entra_allowed_client_ids": []})
    with pytest.raises(HTTPException) as error:
        EntraTokenValidator(s, lambda token: rsa_key.public_key()).validate(token_factory())
    assert error.value.status_code == 503
