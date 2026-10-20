from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.db.models import User
from app.dependencies import rate_limit as rl
from app.dependencies.user import get_current_user_record


# ---------------------------------------------------------------- get_current_user_record


def test_existing_user_is_returned(db, make_user):
    existing = make_user("user_1")
    assert get_current_user_record(clerk_id="user_1", db=db).id == existing.id
    assert db.query(User).count() == 1


def test_unknown_user_gets_a_stub_row(db):
    created = get_current_user_record(clerk_id="user_new", db=db)
    assert created.clerk_id == "user_new" and created.email is None
    assert db.query(User).filter_by(clerk_id="user_new").count() == 1


def test_calling_twice_does_not_duplicate(db):
    first = get_current_user_record(clerk_id="user_new", db=db)
    second = get_current_user_record(clerk_id="user_new", db=db)
    assert first.id == second.id and db.query(User).count() == 1


def test_lost_race_returns_the_row_the_other_request_created(db, make_user, monkeypatch):
    winner = make_user("user_race")
    real_scalar = db.scalar
    calls = {"n": 0}

    def scalar(stmt, *a, **k):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_scalar(stmt, *a, **k)

    def commit():
        raise IntegrityError("insert", {}, Exception("duplicate clerk_id"))

    monkeypatch.setattr(db, "scalar", scalar)
    monkeypatch.setattr(db, "commit", commit)
    assert get_current_user_record(clerk_id="user_race", db=db).id == winner.id


# ---------------------------------------------------------------- rate_limit


USER = SimpleNamespace(id="u-1")


@pytest.fixture()
def script(monkeypatch):
    calls = []
    result = {"value": (1, 60)}

    def fake(keys, args):
        calls.append((keys, args))
        value = result["value"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(rl, "_CHECK_SCRIPT", fake)
    return SimpleNamespace(calls=calls, result=result)


def test_under_the_limit_passes(script):
    script.result["value"] = (3, 55)
    assert rl.rate_limit("things", limit=3, window_seconds=60)(USER) is None


def test_key_is_scoped_by_name_and_user(script):
    rl.rate_limit("things", limit=3, window_seconds=60)(USER)
    keys, args = script.calls[0]
    assert keys == ["rl:things:u-1"] and args == [60]


def test_over_the_limit_is_429_with_retry_after(script):
    script.result["value"] = (4, 42)
    with pytest.raises(HTTPException) as err:
        rl.rate_limit("things", limit=3, window_seconds=60)(USER)
    assert err.value.status_code == 429
    assert err.value.headers["Retry-After"] == "42"
    assert "3 requests per 60s" in err.value.detail and "42s" in err.value.detail


def test_exactly_at_the_limit_still_passes(script):
    script.result["value"] = (3, 10)
    assert rl.rate_limit("things", limit=3, window_seconds=60)(USER) is None


def test_redis_outage_fails_open(script):
    script.result["value"] = ConnectionError("redis down")
    assert rl.rate_limit("things", limit=1, window_seconds=60)(USER) is None
