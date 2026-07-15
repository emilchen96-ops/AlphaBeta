"""SQLAlchemy 2.x asynchronous database infrastructure."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from starlette.requests import Request

from alphadesk_api.core.config import Settings


class Base(DeclarativeBase):
    """Empty M01 metadata base; business models begin in M02."""


class DependencyProbe(Protocol):
    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class DatabaseService:
    """Own the async engine and session factory without domain dependencies."""

    def __init__(self, settings: Settings) -> None:
        self._timeout = settings.dependency_timeout_seconds
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_recycle=1800,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def ping(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            return True
        except (TimeoutError, OSError, ConnectionError):
            return False
        except Exception as exc:
            if exc.__class__.__module__.startswith(("sqlalchemy", "asyncpg")):
                return False
            raise

    async def close(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency kept at the infrastructure boundary."""

    database: DatabaseService = request.app.state.database
    async for session in database.session():
        yield session
