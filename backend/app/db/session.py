from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

from app.config.secrets import settings

# NEON_DB_CONNECT is unset in the v1 (Mongo/Modal) default config; the engine
# is only created lazily so importing this module never requires it.
#
# The laziness is also what makes the RQ worker fork-safe, so do not turn this into a
# module-level create_engine(). The worker imports this module at boot but never touches
# the database itself; the engine is therefore built inside each forked work-horse. If
# the parent built the pool first, every child would inherit the same open sockets and
# two processes would talk over one Postgres connection.
_engine = None
SessionLocal = None


def get_engine():
    global _engine, SessionLocal
    if _engine is None:
        if not settings.NEON_DB_CONNECT:
            raise RuntimeError("NEON_DB_CONNECT is not set — required for PIPELINE=v2")
        _engine = create_engine(settings.NEON_DB_CONNECT, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session():
    if SessionLocal is None:
        get_engine()
    return SessionLocal()


def get_db():
    """FastAPI dependency."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    if SessionLocal is None:
        get_engine()
        
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        # A rollback on a connection the server already dropped raises, which would
        # replace the real error with a confusing OperationalError. Keep the original.
        try:
            session.rollback()
        except Exception:
            session.invalidate()
        raise
    finally:
        session.close()
