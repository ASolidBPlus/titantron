"""add image_tag to video_items

Revision ID: 7821593ad505
Revises: ac58ab128395
Create Date: 2026-02-13 03:55:51.364840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7821593ad505'
down_revision: Union[str, Sequence[str], None] = 'ac58ab128395'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('video_items', sa.Column('image_tag', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('video_items', 'image_tag')
