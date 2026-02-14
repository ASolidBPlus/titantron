"""add_wrestler_alter_egos

Revision ID: 41fd3d6cdfb0
Revises: de34c4501ffc
Create Date: 2026-02-13 08:12:33.671132

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migration_helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '41fd3d6cdfb0'
down_revision: Union[str, Sequence[str], None] = 'de34c4501ffc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists('wrestlers', 'alter_egos'):
        op.add_column('wrestlers', sa.Column('alter_egos', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('wrestlers', 'alter_egos')
