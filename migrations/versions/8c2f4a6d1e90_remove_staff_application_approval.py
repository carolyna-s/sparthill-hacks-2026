"""Remove staff application-approval metadata and accept existing submissions.

Revision ID: 8c2f4a6d1e90
Revises: f6a1b9d4e820
Create Date: 2026-10-24 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8c2f4a6d1e90"
down_revision = "f6a1b9d4e820"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE application SET status = 'accepted' WHERE status = 'submitted'")
    with op.batch_alter_table("application", schema=None) as batch_op:
        batch_op.drop_column("reviewed_by_id")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("staff_notes")


def downgrade():
    with op.batch_alter_table("application", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reviewed_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("staff_notes", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "application_reviewed_by_id_fkey", "user", ["reviewed_by_id"], ["id"]
        )
