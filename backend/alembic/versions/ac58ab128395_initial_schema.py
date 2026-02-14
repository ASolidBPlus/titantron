"""initial schema

Revision ID: ac58ab128395
Revises:
Create Date: 2026-02-12 23:59:07.897070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migration_helpers import table_exists


# revision identifiers, used by Alembic.
revision: str = 'ac58ab128395'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if not table_exists('promotions'):
        op.create_table('promotions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cagematch_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('abbreviation', sa.String(), nullable=True),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('last_scraped', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cagematch_id')
        )
    if not table_exists('scrape_cache'):
        op.create_table('scrape_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url')
        )
    if not table_exists('wrestlers'):
        op.create_table('wrestlers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cagematch_wrestler_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('is_linked', sa.Boolean(), nullable=False),
        sa.Column('last_scraped', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cagematch_wrestler_id')
        )
    if not table_exists('events'):
        op.create_table('events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cagematch_event_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('promotion_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('arena', sa.String(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('votes', sa.Integer(), nullable=True),
        sa.Column('last_scraped', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cagematch_event_id')
        )
    if not table_exists('libraries'):
        op.create_table('libraries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jellyfin_library_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('promotion_id', sa.Integer(), nullable=False),
        sa.Column('last_synced', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jellyfin_library_id')
        )
    if not table_exists('matches'):
        op.create_table('matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cagematch_match_id', sa.Integer(), nullable=True),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('match_number', sa.Integer(), nullable=False),
        sa.Column('match_type', sa.String(), nullable=True),
        sa.Column('stipulation', sa.String(), nullable=True),
        sa.Column('title_name', sa.String(), nullable=True),
        sa.Column('result', sa.String(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('votes', sa.Integer(), nullable=True),
        sa.Column('duration', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if not table_exists('video_items'):
        op.create_table('video_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jellyfin_item_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('filename', sa.String(), nullable=True),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('duration_ticks', sa.BigInteger(), nullable=True),
        sa.Column('date_added', sa.DateTime(), nullable=True),
        sa.Column('premiere_date', sa.DateTime(), nullable=True),
        sa.Column('extracted_date', sa.Date(), nullable=True),
        sa.Column('media_source_id', sa.String(), nullable=True),
        sa.Column('has_trickplay', sa.Boolean(), nullable=False),
        sa.Column('library_id', sa.Integer(), nullable=False),
        sa.Column('matched_event_id', sa.Integer(), nullable=True),
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('match_status', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ),
        sa.ForeignKeyConstraint(['matched_event_id'], ['events.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jellyfin_item_id')
        )
    if not table_exists('chapters'):
        op.create_table('chapters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_item_id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('start_ticks', sa.BigInteger(), nullable=False),
        sa.Column('end_ticks', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ),
        sa.ForeignKeyConstraint(['video_item_id'], ['video_items.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if not table_exists('match_participants'):
        op.create_table('match_participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('wrestler_id', sa.Integer(), nullable=False),
        sa.Column('side', sa.Integer(), nullable=True),
        sa.Column('is_winner', sa.Boolean(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ),
        sa.ForeignKeyConstraint(['wrestler_id'], ['wrestlers.id'], ),
        sa.PrimaryKeyConstraint('id')
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('match_participants')
    op.drop_table('chapters')
    op.drop_table('video_items')
    op.drop_table('matches')
    op.drop_table('libraries')
    op.drop_table('events')
    op.drop_table('wrestlers')
    op.drop_table('scrape_cache')
    op.drop_table('promotions')
