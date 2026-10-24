"""Allow account deletion while preserving anonymized audit history.

Revision ID: ab72c4e9d301
Revises: 9c37f0a1b6de
Create Date: 2026-10-24 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ab72c4e9d301"
down_revision = "9c37f0a1b6de"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.add_column(sa.Column("actor_name", sa.String(length=120), nullable=True))
        batch_op.alter_column("actor_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "UPDATE audit_log SET actor_name = "
        "(SELECT name FROM \"user\" WHERE \"user\".id = audit_log.actor_id)"
    )


def downgrade():
    op.execute("DELETE FROM audit_log WHERE actor_id IS NULL")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.alter_column("actor_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("actor_name")
