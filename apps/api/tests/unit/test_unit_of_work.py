from typing import Any, cast

import pytest

from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


class FakeSession:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


def uow_for(session: FakeSession) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(cast(Any, lambda: session))


@pytest.mark.asyncio
async def test_uow_commits_and_closes_session() -> None:
    session = FakeSession()
    async with uow_for(session) as uow:
        await uow.commit()
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


@pytest.mark.asyncio
async def test_uow_rolls_back_on_body_exception_and_closes() -> None:
    session = FakeSession()
    with pytest.raises(ValueError, match="stop"):
        async with uow_for(session):
            raise ValueError("stop")
    assert session.rollbacks == 1
    assert session.closes == 1


@pytest.mark.asyncio
async def test_uow_rolls_back_failed_commit_and_closes() -> None:
    session = FakeSession(fail_commit=True)
    with pytest.raises(RuntimeError, match="commit failed"):
        async with uow_for(session) as uow:
            await uow.commit()
    assert session.rollbacks == 1
    assert session.closes == 1
