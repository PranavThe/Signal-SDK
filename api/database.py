from __future__ import annotations

from collections.abc import AsyncGenerator
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import settings
from api.db_url import normalize_database_url


database_url, connect_args = normalize_database_url(settings.database_url)

engine = create_async_engine(
    database_url,
    connect_args=connect_args,
    poolclass=pool.NullPool,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
