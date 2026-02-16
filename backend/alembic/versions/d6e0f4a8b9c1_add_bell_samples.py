"""add bell_samples table

Revision ID: d6e0f4a8b9c1
Revises: c5d9e3f6a7b8
Create Date: 2026-02-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migration_helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = 'd6e0f4a8b9c1'
down_revision: Union[str, Sequence[str], None] = 'c5d9e3f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists('bell_samples'):
        op.create_table('bell_samples',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('video_item_id', sa.Integer(), nullable=False),
            sa.Column('start_ticks', sa.BigInteger(), nullable=False),
            sa.Column('end_ticks', sa.BigInteger(), nullable=False),
            sa.Column('label', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.ForeignKeyConstraint(['video_item_id'], ['video_items.id']),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade() -> None:
    op.drop_table('bell_samples')
