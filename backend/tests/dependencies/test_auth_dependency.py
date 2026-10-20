"""Clerk session-token verification, using real RS256 tokens signed with a throwaway key."""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.dependencies.auth as auth


def make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_for(private_key, kid):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update(kid=kid, use="sig", alg="RS256")
    return {"keys": [jwk]}


@pytest.fixture()
def signer(monkeypatch):
    key = make_key()

    async def fake_jwks():
        return jwks_for(key, "kid-1")

    monkeypatch.setattr(auth, "get_jwks", fake_jwks)

    def sign(claims=None, kid="kid-1", private_key=None, **overrides):
        now = int(time.time())
        payload = {"sub": "user_123", "iat": now, "exp": now + 60, "azp": "https://clippper.fyi"}
        payload.update(claims or {})
        payload.update(overrides)
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(payload, private_key or key, algorithm="RS256", headers={"kid": kid})

    return sign


@pytest.fixture()
def api():
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(clerk_id: str = Depends(auth.get_current_user)):
        return {"clerk_id": clerk_id}

    return TestClient(app)


def call(api, token=None, header=None):
    headers = {}
    if header is not None:
        headers["Authorization"] = header
    elif token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return api.get("/whoami", headers=headers)


def test_valid_token_returns_the_clerk_id(api, signer):
    resp = call(api, signer())
    assert resp.status_code == 200 and resp.json() == {"clerk_id": "user_123"}


def test_missing_header_is_401(api):
    resp = call(api)
    assert resp.status_code == 401 and resp.json()["detail"] == "Missing authorization header"


@pytest.mark.parametrize("header", ["Token abc", "bearer abc", "Basic abc", ""])
def test_non_bearer_header_is_401(api, header):
    assert call(api, header=header).status_code == 401


def test_garbage_token_is_401(api, signer):
    assert call(api, "not.a.jwt").status_code == 401


def test_expired_token_is_rejected_with_its_own_message(api, signer):
    now = int(time.time())
    resp = call(api, signer(iat=now - 600, exp=now - 300))
    assert resp.status_code == 401 and resp.json()["detail"] == "Token expired"


def test_slightly_expired_token_is_accepted_within_leeway(api, signer):
    now = int(time.time())
    assert call(api, signer(iat=now - 100, exp=now - 5)).status_code == 200


def test_token_signed_by_a_different_key_is_rejected(api, signer):
    assert call(api, signer(private_key=make_key())).status_code == 401


def test_unknown_key_id_is_rejected(api, signer):
    resp = call(api, signer(kid="someone-elses-key"))
    assert resp.status_code == 401 and resp.json()["detail"] == "Invalid token key"


def test_token_from_an_unlisted_origin_is_rejected(api, signer):
    resp = call(api, signer(azp="https://evil.example"))
    assert resp.status_code == 401


@pytest.mark.parametrize("origin", sorted(auth.ALLOWED_PARTIES))
def test_every_listed_origin_is_accepted(api, signer, origin):
    assert call(api, signer(azp=origin)).status_code == 200


def test_token_without_azp_is_accepted(api, signer):
    assert call(api, signer(azp=None)).status_code == 200


def test_token_without_subject_is_rejected(api, signer):
    resp = call(api, signer(sub=None))
    assert resp.status_code == 401


def test_unsigned_alg_none_token_is_rejected(api, signer):
    token = jwt.encode({"sub": "user_123", "exp": int(time.time()) + 60}, key=None, algorithm="none", headers={"kid": "kid-1"})
    assert call(api, token).status_code == 401


# ---------------------------------------------------------------- JWKS fetching


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload, self.text = status, payload or {"keys": []}, "body"

    def json(self):
        return self._payload


class FakeAsyncClient:
    last_url = None
    response = FakeResponse()

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        FakeAsyncClient.last_url = url
        return FakeAsyncClient.response


@pytest.fixture()
def jwks_http(monkeypatch):
    monkeypatch.setattr(auth, "_jwks_cache", None)
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.last_url = None
    FakeAsyncClient.response = FakeResponse(payload={"keys": [{"kid": "k"}]})
    return FakeAsyncClient


@pytest.mark.anyio
async def test_jwks_is_fetched_once_then_cached(jwks_http):
    first = await auth.get_jwks()
    jwks_http.last_url = None
    second = await auth.get_jwks()
    assert first == second == {"keys": [{"kid": "k"}]}
    assert jwks_http.last_url is None  # second call never hit the network


@pytest.mark.anyio
async def test_jwks_failure_raises_500_and_is_not_cached(jwks_http):
    from fastapi import HTTPException

    jwks_http.response = FakeResponse(status=503)
    with pytest.raises(HTTPException) as err:
        await auth.get_jwks()
    assert err.value.status_code == 500
    assert auth._jwks_cache is None
