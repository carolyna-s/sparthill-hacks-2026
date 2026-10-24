"""Automatically accept applications previously rejected by staff.

Revision ID: 93ad71ce4b26
Revises: 8c2f4a6d1e90
Create Date: 2026-10-24 13:15:00.000000
"""

from alembic import op


revision = "93ad71ce4b26"
down_revision = "8c2f4a6d1e90"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE application SET status = 'accepted' WHERE status = 'rejected'")


def downgrade():
    pass
