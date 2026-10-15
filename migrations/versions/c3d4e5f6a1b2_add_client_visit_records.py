"""Add client_visit_records table for Multimodal Proof-of-Execution & Debrief

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-10-11 19:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'client_visit_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('task_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('org_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('user_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('client_name', sa.String(length=200), nullable=False),
        sa.Column('visit_lat', sa.Float(), nullable=False),
        sa.Column('visit_lon', sa.Float(), nullable=False),
        sa.Column('distance_from_site_meters', sa.Float(), nullable=False),
        sa.Column('geo_otp_verified', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('photo_evidence_hash', sa.String(length=64), nullable=True),
        sa.Column('photo_verification_status', sa.String(length=32), nullable=False, server_default='VERIFIED'),
        sa.Column('photo_analysis_json', sa.JSON(), nullable=True),
        sa.Column('voice_audio_hash', sa.String(length=64), nullable=True),
        sa.Column('crm_debrief_json', sa.JSON(), nullable=True),
        sa.Column('trust_block_hash', sa.String(length=64), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
    )
    op.create_index('ix_visit_org_client', 'client_visit_records', ['org_id', 'client_name'])
    op.create_index('ix_visit_user_completed', 'client_visit_records', ['user_id', 'completed_at'])


def downgrade() -> None:
    op.drop_index('ix_visit_user_completed', table_name='client_visit_records')
    op.drop_index('ix_visit_org_client', table_name='client_visit_records')
    op.drop_table('client_visit_records')
