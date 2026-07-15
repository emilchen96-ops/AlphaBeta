from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.helpers import require_test_database_url


@pytest_asyncio.fixture
async def test_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(require_test_database_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with test_engine.connect() as connection:
        outer_transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield factory
        await outer_transaction.rollback()
