"""Track mentor confirmation for admin-approved capacity overrides.

Revision ID: f6a1b9d4e820
Revises: d4b8c3a19f20
Create Date: 2026-10-24 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a1b9d4e820"
down_revision = "d4b8c3a19f20"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("match", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mentor_confirmed_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("match", schema=None) as batch_op:
        batch_op.drop_column("mentor_confirmed_at")
