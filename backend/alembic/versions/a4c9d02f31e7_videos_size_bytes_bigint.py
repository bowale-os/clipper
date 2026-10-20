"""videos.size_bytes -> bigint

Revision ID: a4c9d02f31e7
Revises: 1f6b3e87bd11
Create Date: 2026-07-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4c9d02f31e7'
down_revision: Union[str, Sequence[str], None] = '1f6b3e87bd11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('videos', 'size_bytes', type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('videos', 'size_bytes', type_=sa.Integer(), existing_type=sa.BigInteger())
