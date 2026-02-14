"""add audio_skip_reason to analysis_results

Revision ID: b4c8d2e3f5a6
Revises: a3b7c9d1e2f4
Create Date: 2026-02-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migration_helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'b4c8d2e3f5a6'
down_revision: Union[str, None] = 'a3b7c9d1e2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists('analysis_results', 'audio_skip_reason'):
        with op.batch_alter_table('analysis_results') as batch_op:
            batch_op.add_column(sa.Column('audio_skip_reason', sa.String(), nullable=True))


def downgrade() -> None:
    if column_exists('analysis_results', 'audio_skip_reason'):
        with op.batch_alter_table('analysis_results') as batch_op:
            batch_op.drop_column('audio_skip_reason')
