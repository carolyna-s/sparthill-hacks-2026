"""Supabase-only: email_log, RLS on the tables added since, and the uploads bucket.

Revision ID: b9e4d2a7c315
Revises: f6a1b9d4e820
Create Date: 2026-10-24 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b9e4d2a7c315"
down_revision = "f6a1b9d4e820"
branch_labels = None
depends_on = None

# Created after 31ed905ca990 turned RLS on for every table, so they were left exposed to the
# public Data API. email_log is new here.
NEW_RLS_TABLES = ("meeting", "audit_log", "match_override_request", "email_log")

BUCKET = "uploads"  # must match SUPABASE_STORAGE_BUCKET's default in app/config.py


def _postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade():
    op.create_table(
        "email_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=True),
        sa.Column("backend", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("email_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_email_log_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_email_log_created_at"), ["created_at"], unique=False)

    if _postgres():
        for table in NEW_RLS_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        # Private bucket for uploads (app/storage.py). Only on Supabase, where storage exists.
        op.execute(f"""
            DO $$ BEGIN
              IF to_regclass('storage.buckets') IS NOT NULL THEN
                INSERT INTO storage.buckets (id, name, public, file_size_limit)
                VALUES ('{BUCKET}', '{BUCKET}', false, 10485760)
                ON CONFLICT (id) DO NOTHING;
              END IF;
            END $$;
        """)


def downgrade():
    # The bucket is left in place: deleting it would need emptying it first, and loses files.
    if _postgres():
        for table in ("meeting", "audit_log", "match_override_request"):
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    with op.batch_alter_table("email_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_email_log_created_at"))
        batch_op.drop_index(batch_op.f("ix_email_log_user_id"))
    op.drop_table("email_log")
