"""Add field_task_records table for AskforWrite Autonomous Dispatch & Route Optimizer

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-10-11 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a1'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'field_task_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('assigned_to_user_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('title', sa.String(length=250), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('client_name', sa.String(length=200), nullable=False),
        sa.Column('destination_lat', sa.Float(), nullable=False),
        sa.Column('destination_lon', sa.Float(), nullable=False),
        sa.Column('priority', sa.String(length=32), nullable=False, server_default='NORMAL'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING'),
        sa.Column('route_sequence_index', sa.Integer(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_field_task_org_status', 'field_task_records', ['org_id', 'status'])
    op.create_index('ix_field_task_assigned_status', 'field_task_records', ['assigned_to_user_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_field_task_assigned_status', table_name='field_task_records')
    op.drop_index('ix_field_task_org_status', table_name='field_task_records')
    op.drop_table('field_task_records')
