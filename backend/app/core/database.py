from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata for application-owned MySQL tables."""


_session_factory: async_sessionmaker[AsyncSession] | None = None


class DatabaseManager:
    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        global _session_factory
        _session_factory = self.session_factory

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a transaction-capable session managed by the current application DB manager."""
    if _session_factory is None:
        raise RuntimeError("database session factory is not configured")

    async with _session_factory() as session:
        yield session
