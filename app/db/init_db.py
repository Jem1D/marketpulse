"""Initialize the database schema and pgvector extension."""

from sqlalchemy import text

from app.db.session import engine, Base
from app.db import models  # noqa: F401 — registers models with Base


def init():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    print("Database initialized: pgvector extension enabled, tables created.")


if __name__ == "__main__":
    init()
