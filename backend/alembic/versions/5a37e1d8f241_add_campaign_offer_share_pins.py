"""Persist pinned offer shares.

Revision ID: 5a37e1d8f241
Revises: 9c821c3d2f40
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5a37e1d8f241"
down_revision: Union[str, None] = "9c821c3d2f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_offer_pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "stream_id", "offer_id", name="uq_campaign_offer_pin"),
    )
    op.create_index("ix_campaign_offer_pins_campaign_id", "campaign_offer_pins", ["campaign_id"])
    op.create_index("ix_campaign_offer_pins_stream_id", "campaign_offer_pins", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_offer_pins_stream_id", table_name="campaign_offer_pins")
    op.drop_index("ix_campaign_offer_pins_campaign_id", table_name="campaign_offer_pins")
    op.drop_table("campaign_offer_pins")
