"""Add staff match confirmation flow and admin capacity override requests.

Revision ID: d4b8c3a19f20
Revises: ab72c4e9d301
Create Date: 2026-10-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d4b8c3a19f20"
down_revision = "ab72c4e9d301"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "match_override_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mentee_id", sa.Integer(), nullable=False),
        sa.Column("mentor_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["decided_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["match_id"], ["match.id"]),
        sa.ForeignKeyConstraint(["mentee_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["mentor_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["requested_by_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_override_request_mentee_id", "match_override_request", ["mentee_id"])
    op.create_index("ix_match_override_request_mentor_id", "match_override_request", ["mentor_id"])
    op.create_index("ix_match_override_request_status", "match_override_request", ["status"])


def downgrade():
    op.drop_index("ix_match_override_request_status", table_name="match_override_request")
    op.drop_index("ix_match_override_request_mentor_id", table_name="match_override_request")
    op.drop_index("ix_match_override_request_mentee_id", table_name="match_override_request")
    op.drop_table("match_override_request")
