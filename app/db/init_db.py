"""Initialize the database schema and pgvector extension."""

from sqlalchemy import text

from app.db.session import engine, Base
from app.db import models  # noqa: F401 — registers models with Base


def _drop_correlation_reports_if_wrong_embedding_dim():
    """Recreate table when switching embedding model (e.g. OpenAI 1536 -> Ollama 768)."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                WHERE c.relname = 'correlation_reports'
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                """
            )
        ).fetchone()
        if row and row[0] and "768" not in row[0]:
            conn.execute(text("DROP TABLE correlation_reports"))
            conn.commit()


def init():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    _drop_correlation_reports_if_wrong_embedding_dim()
    Base.metadata.create_all(bind=engine)
    print("Database initialized: pgvector extension enabled, tables created.")


if __name__ == "__main__":
    init()
