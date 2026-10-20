"""The Clerk webhook. Requests are signed with the real svix scheme."""
import base64
import hashlib
import hmac
import json
import time

import pytest
from app.api import auth as auth_api
from app.config.secrets import settings
from app.db.models import User


def signed(event: dict, secret=None, msg_id="msg_1", tamper=False):
    """Sign like Clerk does: HMAC-SHA256 over "<id>.<timestamp>.<body>" with the decoded key."""
    payload = json.dumps(event)
    key = base64.b64decode((secret or settings.CLERK_WEBHOOK_SIGNING_SECRET).removeprefix("whsec_"))
    ts = str(int(time.time()))
    digest = hmac.new(key, f"{msg_id}.{ts}.{payload}".encode(), hashlib.sha256).digest()
    signature = "v1," + base64.b64encode(digest).decode()
    if tamper:
        payload = payload.replace("Ada", "Eve")
    headers = {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": signature, "content-type": "application/json"}
    return payload, headers


def created(clerk_id="user_abc", first="Ada", last="Lovelace", emails=None):
    emails = [{"email_address": "ada@example.com"}] if emails is None else emails
    return {
        "type": "user.created",
        "data": {"id": clerk_id, "first_name": first, "last_name": last, "email_addresses": emails},
    }


@pytest.fixture()
def pg_insert_for_sqlite(monkeypatch):
    # create_user upserts with the Postgres dialect's insert(); SQLite understands the
    # same ON CONFLICT clause through its own insert construct.
    from sqlalchemy.dialects.sqlite import insert

    monkeypatch.setattr(auth_api, "pg_insert", insert)


def post(client, event, **kw):
    payload, headers = signed(event, **kw)
    return client.post("/auth/clerk-auth", content=payload, headers=headers)


def test_valid_user_created_event_creates_the_user(client, db, pg_insert_for_sqlite):
    resp = post(client, created())
    assert resp.status_code == 200 and resp.json()["success"] is True
    user = db.query(User).filter_by(clerk_id="user_abc").one()
    assert user.email == "ada@example.com" and user.name == "Ada Lovelace"
    assert resp.json()["db_id"] == str(user.id)


def test_replayed_event_updates_instead_of_duplicating(client, db, pg_insert_for_sqlite):
    post(client, created(first="Ada"))
    post(client, created(first="Augusta"), msg_id="msg_2")
    db.expire_all()
    users = db.query(User).filter_by(clerk_id="user_abc").all()
    assert len(users) == 1 and users[0].name == "Augusta Lovelace"


def test_webhook_backfills_a_stub_user_made_by_the_api(client, db, make_user, pg_insert_for_sqlite):
    stub = make_user("user_abc", email=None)
    stub_id = stub.id
    post(client, created())
    db.expire_all()
    row = db.query(User).filter_by(clerk_id="user_abc").one()
    assert row.id == stub_id and row.email == "ada@example.com"


def test_missing_names_are_tolerated(client, db, pg_insert_for_sqlite):
    resp = post(client, created(first=None, last=None))
    assert resp.status_code == 200
    assert db.query(User).filter_by(clerk_id="user_abc").one().name == ""


@pytest.mark.parametrize("emails", [[], [{"email_address": ""}], [{}]])
def test_event_without_an_email_is_rejected(client, db, pg_insert_for_sqlite, emails):
    resp = post(client, created(emails=emails))
    assert resp.status_code == 500
    assert db.query(User).count() == 0


def test_other_event_types_are_acknowledged_and_ignored(client, db):
    resp = post(client, {"type": "user.updated", "data": {"id": "user_abc"}})
    assert resp.status_code == 200 and "Ignored" in resp.json()["message"]
    assert db.query(User).count() == 0


def test_tampered_payload_is_rejected(client, db):
    payload, headers = signed(created(), tamper=True)
    resp = client.post("/auth/clerk-auth", content=payload, headers=headers)
    assert resp.status_code == 400
    assert db.query(User).count() == 0


def test_wrong_signing_secret_is_rejected(client, db):
    other = "whsec_" + "b3RoZXItc2VjcmV0LW90aGVyLXNlY3JldA=="
    resp = post(client, created(), secret=other)
    assert resp.status_code == 400
    assert db.query(User).count() == 0


def test_unsigned_request_is_rejected(client, db):
    resp = client.post("/auth/clerk-auth", content=json.dumps(created()))
    assert resp.status_code == 400
    assert db.query(User).count() == 0
