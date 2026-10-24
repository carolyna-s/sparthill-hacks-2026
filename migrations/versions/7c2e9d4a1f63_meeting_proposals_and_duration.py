"""meeting: either side proposes a time block, the other confirms it

Revision ID: 7c2e9d4a1f63
Revises: 5a7e3c1d9b42
Create Date: 2026-10-24 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c2e9d4a1f63'
down_revision = '5a7e3c1d9b42'
branch_labels = None
depends_on = None


def upgrade():
    # Existing meetings were booked directly by the mentor, so they count as confirmed.
    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(10), nullable=False, server_default='confirmed'))
        batch_op.add_column(sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='30'))


def downgrade():
    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.drop_column('duration_minutes')
        batch_op.drop_column('status')
