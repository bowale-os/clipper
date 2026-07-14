from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.secrets import settings

# NEON_DB_CONNECT is unset in the v1 (Mongo/Modal) default config; the engine
# is only created lazily so importing this module never requires it.
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
