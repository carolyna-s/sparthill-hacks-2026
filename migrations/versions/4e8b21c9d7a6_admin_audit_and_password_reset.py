"""Add admin audit log and required password reset flag.

Revision ID: 4e8b21c9d7a6
Revises: f1a9c3e5b7d2
Create Date: 2026-10-24 09:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "4e8b21c9d7a6"
down_revision = "f1a9c3e5b7d2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("must_reset_password", sa.Boolean(), server_default=sa.false(), nullable=False)
        )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("actor_role", sa.String(length=10), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index("ix_audit_log_actor_id", ["actor_id"], unique=False)
        batch_op.create_index("ix_audit_log_created_at", ["created_at"], unique=False)


def downgrade():
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_log_created_at")
        batch_op.drop_index("ix_audit_log_actor_id")
    op.drop_table("audit_log")
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("must_reset_password")
