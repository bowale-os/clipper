from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.dependencies.auth import get_current_user


def get_current_user_record(
    clerk_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    user = db.scalar(select(User).where(User.clerk_id == clerk_id))
    if user is None:
        # The Clerk webhook may not have fired for users created before it existed.
        user = User(clerk_id=clerk_id)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent request created the row first.
            db.rollback()
            user = db.scalar(select(User).where(User.clerk_id == clerk_id))
    return user
