"""add wrestler rating and votes

Revision ID: 627445f9e6e0
Revises: 41fd3d6cdfb0
Create Date: 2026-02-13 10:28:32.772868

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '627445f9e6e0'
down_revision: Union[str, Sequence[str], None] = '41fd3d6cdfb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('wrestlers', sa.Column('rating', sa.Float(), nullable=True))
    op.add_column('wrestlers', sa.Column('votes', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('wrestlers', 'votes')
    op.drop_column('wrestlers', 'rating')
