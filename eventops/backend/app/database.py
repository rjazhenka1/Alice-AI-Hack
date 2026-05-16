"""Database setup for EventOps backend."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./eventops.db")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name().startswith("postgresql"):
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector(256)"))
            await conn.execute(text("DROP INDEX IF EXISTS ix_chunks_embedding"))
            await conn.execute(text("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(256)"))
            await conn.execute(
                text(
                    "CREATE INDEX ix_chunks_embedding "
                    "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
                    "WITH (m = 16, ef_construction = 64)"
                )
            )
