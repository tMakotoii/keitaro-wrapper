"""Initial migration: campaign_operations and campaign_offers tables

Revision ID: 4e564df2ae2e
Revises:
Create Date: 2026-11-19 15:09:06.713567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e564df2ae2e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'campaign_operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('operation_type', sa.String(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('campaign_name', sa.String(), nullable=False),
        sa.Column('user', sa.String(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_campaign_operations_id'), 'campaign_operations', ['id'], unique=False)

    op.create_table(
        'campaign_offers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('stream_id', sa.Integer(), nullable=False),
        sa.Column('offer_id', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_campaign_offers_id'), 'campaign_offers', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_campaign_offers_id'), table_name='campaign_offers')
    op.drop_table('campaign_offers')
    op.drop_index(op.f('ix_campaign_operations_id'), table_name='campaign_operations')
    op.drop_table('campaign_operations')
