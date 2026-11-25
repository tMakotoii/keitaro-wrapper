"""Persist staged campaign offer changes.

Revision ID: 9c821c3d2f40
Revises: 4e564df2ae2e
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c821c3d2f40"
down_revision: Union[str, None] = "4e564df2ae2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_offer_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "stream_id", "offer_id", name="uq_campaign_offer_draft"),
    )
    op.create_index("ix_campaign_offer_drafts_campaign_id", "campaign_offer_drafts", ["campaign_id"])
    op.create_index("ix_campaign_offer_drafts_stream_id", "campaign_offer_drafts", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_offer_drafts_stream_id", table_name="campaign_offer_drafts")
    op.drop_index("ix_campaign_offer_drafts_campaign_id", table_name="campaign_offer_drafts")
    op.drop_table("campaign_offer_drafts")
