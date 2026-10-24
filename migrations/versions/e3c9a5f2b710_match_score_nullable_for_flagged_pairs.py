"""match.score is NULL for pairs that fail a hard filter.

The would-be score moves to score_breakdown["fit_if_compatible"], so averages over match.score
only count pairs that can actually meet.

Revision ID: e3c9a5f2b710
Revises: b9e4d2a7c315
Create Date: 2026-10-24 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e3c9a5f2b710"
down_revision = "b9e4d2a7c315"
branch_labels = None
depends_on = None


def _postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade():
    with op.batch_alter_table("match", schema=None) as batch_op:
        batch_op.alter_column("score", existing_type=sa.Float(), nullable=True)
    # Flagged pairs proposed before this kept their would-be score in match.score.
    if _postgres():
        op.execute(
            "UPDATE \"match\" SET score_breakdown = jsonb_set(score_breakdown::jsonb, '{fit_if_compatible}', "
            "to_jsonb(score))::json, score = NULL WHERE score_breakdown::jsonb ? 'filters_failed'"
        )


def downgrade():
    if _postgres():
        op.execute(
            "UPDATE \"match\" SET score = COALESCE((score_breakdown->>'fit_if_compatible')::float, 0) "
            "WHERE score IS NULL"
        )
    else:
        op.execute("UPDATE \"match\" SET score = 0 WHERE score IS NULL")
    with op.batch_alter_table("match", schema=None) as batch_op:
        batch_op.alter_column("score", existing_type=sa.Float(), nullable=False)
