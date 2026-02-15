"""add audio_spectrum to analysis_results

Revision ID: c5d9e3f6a7b8
Revises: b4c8d2e3f5a6
Create Date: 2026-02-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migration_helpers import column_exists


# revision identifiers, used by Alembic.
revision: str = 'c5d9e3f6a7b8'
down_revision: Union[str, None] = 'b4c8d2e3f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists('analysis_results', 'audio_spectrum'):
        with op.batch_alter_table('analysis_results') as batch_op:
            batch_op.add_column(sa.Column('audio_spectrum', sa.Text(), nullable=True))


def downgrade() -> None:
    if column_exists('analysis_results', 'audio_spectrum'):
        with op.batch_alter_table('analysis_results') as batch_op:
            batch_op.drop_column('audio_spectrum')
