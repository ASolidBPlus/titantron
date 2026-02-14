"""add_library_path_mapping

Revision ID: 9093cf8dfdbc
Revises: 627445f9e6e0
Create Date: 2026-02-14 17:04:05.949695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migration_helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = '9093cf8dfdbc'
down_revision: Union[str, Sequence[str], None] = '627445f9e6e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not column_exists('libraries', 'jellyfin_path'):
        op.add_column('libraries', sa.Column('jellyfin_path', sa.String(), nullable=True))
    if not column_exists('libraries', 'local_path'):
        op.add_column('libraries', sa.Column('local_path', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('libraries', 'local_path')
    op.drop_column('libraries', 'jellyfin_path')
