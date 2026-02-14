"""add_analysis_results

Revision ID: 2f64eddb7849
Revises: 9093cf8dfdbc
Create Date: 2026-02-14 17:06:13.295890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f64eddb7849'
down_revision: Union[str, Sequence[str], None] = '9093cf8dfdbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('analysis_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('video_item_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('total_steps', sa.Integer(), nullable=False),
    sa.Column('message', sa.String(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('visual_detections', sa.Text(), nullable=True),
    sa.Column('audio_detections', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['video_item_id'], ['video_items.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('video_item_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('analysis_results')
