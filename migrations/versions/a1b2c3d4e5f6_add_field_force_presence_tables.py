"""Add geofence_definitions and field_attendance_records tables for AskforWrite Field Force Engine

Revision ID: a1b2c3d4e5f6
Revises: 9c0d1e2f3a4b
Create Date: 2026-10-11 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9c0d1e2f3a4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'geofence_definitions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('radius_meters', sa.Float(), nullable=False, server_default='150.0'),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'field_attendance_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('user_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('accuracy_meters', sa.Float(), nullable=False),
        sa.Column('altitude', sa.Float(), nullable=True),
        sa.Column('device_fingerprint', sa.String(length=128), nullable=False),
        sa.Column('is_mock_location_detected', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('wifi_bssid_hash', sa.String(length=64), nullable=True),
        sa.Column('cell_tower_id', sa.String(length=64), nullable=True),
        sa.Column('geofence_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('verification_notes', sa.Text(), nullable=True),
        sa.Column('trust_block_hash', sa.String(length=64), nullable=True),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
    )
    op.create_index('ix_attendance_user_ts', 'field_attendance_records', ['user_id', 'timestamp'])
    op.create_index('ix_attendance_org_ts', 'field_attendance_records', ['org_id', 'timestamp'])


def downgrade() -> None:
    op.drop_index('ix_attendance_org_ts', table_name='field_attendance_records')
    op.drop_index('ix_attendance_user_ts', table_name='field_attendance_records')
    op.drop_table('field_attendance_records')
    op.drop_table('geofence_definitions')
