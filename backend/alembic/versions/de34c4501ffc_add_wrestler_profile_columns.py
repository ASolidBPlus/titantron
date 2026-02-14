"""add_wrestler_profile_columns

Revision ID: de34c4501ffc
Revises: 7821593ad505
Create Date: 2026-02-13 06:57:38.532218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migration_helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'de34c4501ffc'
down_revision: Union[str, Sequence[str], None] = '7821593ad505'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    columns = [
        ('wrestlers', 'birth_date', sa.Date()),
        ('wrestlers', 'birth_place', sa.String()),
        ('wrestlers', 'height', sa.String()),
        ('wrestlers', 'weight', sa.String()),
        ('wrestlers', 'style', sa.String()),
        ('wrestlers', 'debut', sa.String()),
        ('wrestlers', 'roles', sa.String()),
        ('wrestlers', 'nicknames', sa.String()),
        ('wrestlers', 'signature_moves', sa.String()),
        ('wrestlers', 'trainers', sa.String()),
    ]
    for table, col, col_type in columns:
        if not column_exists(table, col):
            op.add_column(table, sa.Column(col, col_type, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for col in ['trainers', 'signature_moves', 'nicknames', 'roles', 'debut', 'style', 'weight', 'height', 'birth_place', 'birth_date']:
        op.drop_column('wrestlers', col)
