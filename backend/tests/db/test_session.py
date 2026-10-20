from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

import app.db.session as session_module
from app.db.models import User


def test_get_engine_requires_a_connection_string(monkeypatch):
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module.settings, "NEON_DB_CONNECT", "")
    with pytest.raises(RuntimeError, match="NEON_DB_CONNECT"):
        session_module.get_engine()


def test_get_engine_is_created_lazily_and_reused(monkeypatch):
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "SessionLocal", None)
    monkeypatch.setattr(session_module.settings, "NEON_DB_CONNECT", "sqlite://")
    first = session_module.get_engine()
    assert session_module.get_engine() is first
    assert session_module.SessionLocal is not None
    first.dispose()


def test_get_session_builds_the_factory_on_demand(monkeypatch):
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "SessionLocal", None)
    monkeypatch.setattr(session_module.settings, "NEON_DB_CONNECT", "sqlite://")
    session = session_module.get_session()
    assert session.execute(text("select 1")).scalar() == 1
    session.close()


def test_get_db_yields_a_session_and_closes_it(db_engine):
    gen = session_module.get_db()
    session = next(gen)
    assert session.execute(text("select 1")).scalar() == 1
    closed = MagicMock(wraps=session.close)
    session.close = closed
    with pytest.raises(StopIteration):
        next(gen)
    closed.assert_called_once()


def test_session_scope_commits_on_success(db_engine):
    with session_module.session_scope() as s:
        s.add(User(clerk_id="committed"))
    with session_module.session_scope() as s:
        assert s.query(User).filter_by(clerk_id="committed").count() == 1


def test_session_scope_rolls_back_on_error_and_reraises_the_original(db_engine):
    with pytest.raises(ValueError, match="original"):
        with session_module.session_scope() as s:
            s.add(User(clerk_id="discarded"))
            s.flush()
            raise ValueError("original")
    with session_module.session_scope() as s:
        assert s.query(User).filter_by(clerk_id="discarded").count() == 0


def test_a_failing_rollback_does_not_mask_the_original_error(db_engine, monkeypatch):
    class BrokenSession:
        def __init__(self):
            self.invalidated = False
            self.closed = False

        def commit(self):
            pass

        def rollback(self):
            raise ConnectionError("server closed the connection")

        def invalidate(self):
            self.invalidated = True

        def close(self):
            self.closed = True

    broken = BrokenSession()
    monkeypatch.setattr(session_module, "SessionLocal", lambda: broken)
    with pytest.raises(ValueError, match="real cause"):
        with session_module.session_scope():
            raise ValueError("real cause")
    assert broken.invalidated and broken.closed
