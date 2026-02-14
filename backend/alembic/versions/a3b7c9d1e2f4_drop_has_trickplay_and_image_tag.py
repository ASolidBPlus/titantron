"""drop has_trickplay and image_tag from video_items

Revision ID: a3b7c9d1e2f4
Revises: 2f64eddb7849
Create Date: 2026-02-14 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migration_helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'a3b7c9d1e2f4'
down_revision: Union[str, None] = '2f64eddb7849'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite doesn't support DROP COLUMN before 3.35.0, but we use
    # batch mode which recreates the table.
    cols_to_drop = []
    if column_exists('video_items', 'has_trickplay'):
        cols_to_drop.append('has_trickplay')
    if column_exists('video_items', 'image_tag'):
        cols_to_drop.append('image_tag')

    if cols_to_drop:
        with op.batch_alter_table('video_items') as batch_op:
            for col in cols_to_drop:
                batch_op.drop_column(col)


def downgrade() -> None:
    with op.batch_alter_table('video_items') as batch_op:
        batch_op.add_column(sa.Column('has_trickplay', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('image_tag', sa.String(), nullable=True))
