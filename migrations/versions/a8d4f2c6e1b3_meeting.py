"""meeting: mentor-scheduled meetings shown on both calendars

Revision ID: a8d4f2c6e1b3
Revises: f1a9c3e5b7d2
Create Date: 2026-10-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8d4f2c6e1b3'
down_revision = 'f1a9c3e5b7d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('meeting',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['match_id'], ['match.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_meeting_match_id'), ['match_id'], unique=False)


def downgrade():
    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_meeting_match_id'))

    op.drop_table('meeting')
