"""The assembled FastAPI app: routing table, CORS, error handling, and the auth guard."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROUTES = [
    ("POST", "/auth/clerk-auth"),
    ("POST", "/videos/init"),
    ("POST", "/videos/{video_id}/parts"),
    ("GET", "/videos/{video_id}/upload-status"),
    ("POST", "/videos/complete"),
    ("POST", "/videos/{video_id}/abort"),
    ("GET", "/videos/"),
    ("GET", "/videos/search"),
    ("GET", "/videos/{video_id}/metadata"),
    ("GET", "/videos/{video_id}/moments"),
    ("DELETE", "/videos/{video_id}"),
    ("POST", "/clips/create"),
    ("GET", "/clips"),
    ("GET", "/clips/{clip_id}"),
]


def test_health_route(db_engine):
    resp = TestClient(app).get("/hit-it")
    assert resp.status_code == 200 and "you are home" in resp.json().values()


@pytest.mark.parametrize("method,path", ROUTES)
def test_route_is_registered(method, path):
    paths = app.openapi()["paths"]
    assert path in paths and method.lower() in paths[path]


# Every route except the Clerk webhook must reject callers without a token.
PROTECTED = [(m, p) for m, p in ROUTES if p != "/auth/clerk-auth"]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_need_a_token(db_engine, rate_counter, method, path):
    concrete = path.replace("{video_id}", "00000000-0000-0000-0000-000000000000").replace(
        "{clip_id}", "00000000-0000-0000-0000-000000000000"
    )
    resp = TestClient(app).request(method, concrete)
    assert resp.status_code == 401, f"{method} {path} answered {resp.status_code} without a token"


def test_unhandled_errors_become_a_clean_500(client, user, make_video, monkeypatch):
    v = make_video(user)
    monkeypatch.setattr("app.api.video.get_owned_video", MagicMock(side_effect=RuntimeError("secret internals")))
    resp = client.get(f"/videos/{v.id}/metadata")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error"
    assert body["method"] == "GET" and body["path"].endswith("/metadata")
    assert "secret internals" not in resp.text


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "https://clippper.fyi", "https://www.clippper.fyi", "https://clippper.vercel.app"],
)
def test_cors_allows_the_known_frontends(origin):
    resp = TestClient(app).options(
        "/videos/", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_other_origins():
    resp = TestClient(app).options(
        "/videos/", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in resp.headers


def test_unknown_route_is_404():
    assert TestClient(app).get("/nope").status_code == 404
