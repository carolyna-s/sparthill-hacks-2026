"""Column types that differ between Postgres (Supabase) and SQLite (local dev, tests)."""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

# 384 dims fits small local models (all-MiniLM-L6-v2, gte-small). Changing it needs a migration
# and re-embedding every row.
EMBEDDING_DIM = 384


class Embedding(TypeDecorator):
    """pgvector `vector(dim)` on Postgres; a JSON list of floats elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):
        # pgvector returns numpy arrays or strings depending on version; normalize to list[float].
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            return [float(x) for x in value.strip("[]").split(",") if x]
        return [float(x) for x in value]

    def __repr__(self) -> str:
        return f"Embedding(dim={self.dim})"
