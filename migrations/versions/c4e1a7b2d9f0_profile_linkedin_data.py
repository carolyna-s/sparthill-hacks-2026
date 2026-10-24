"""profile: parsed LinkedIn data

Revision ID: c4e1a7b2d9f0
Revises: 2c50da610bc6
Create Date: 2026-10-23 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e1a7b2d9f0'
down_revision = '2c50da610bc6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('profile', schema=None) as batch_op:
        batch_op.add_column(sa.Column('linkedin_data', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('profile', schema=None) as batch_op:
        batch_op.drop_column('linkedin_data')
