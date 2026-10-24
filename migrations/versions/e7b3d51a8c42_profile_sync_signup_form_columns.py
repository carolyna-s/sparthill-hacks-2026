"""profile: sync sign-up form columns

97249da0ff3f was renamed to 2c50da610bc6 and edited after some databases (Supabase) had already
run it, so those still have its old columns and lack the new ones. This brings any database to
2c50da610bc6's columns, and is a no-op on one that ran the current version.

Revision ID: e7b3d51a8c42
Revises: c4e1a7b2d9f0
Create Date: 2026-10-23 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b3d51a8c42'
down_revision = 'c4e1a7b2d9f0'
branch_labels = None
depends_on = None

ADDED = [
    sa.Column('industry', sa.String(length=120), nullable=True),
    sa.Column('interests', sa.Text(), nullable=True),
    sa.Column('goals_other', sa.Text(), nullable=True),
    sa.Column('looking_for', sa.Text(), nullable=True),
]
REMOVED = ['career_outlook', 'seniority', 'mentoring_style', 'company_types']


def _columns() -> set[str]:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('profile')}


def upgrade():
    existing = _columns()
    with op.batch_alter_table('profile', schema=None) as batch_op:
        for column in ADDED:
            if column.name not in existing:
                batch_op.add_column(column)
        for name in REMOVED:
            if name in existing:
                batch_op.drop_column(name)


def downgrade():
    # 2c50da610bc6 owns these columns; nothing to undo on a database that ran it.
    pass
