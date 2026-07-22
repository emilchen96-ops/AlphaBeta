from datetime import datetime
from typing import cast
from uuid import uuid4

import pytest

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.intraday import (
    IntradayMarketDataImportService,
    IntradayOverviewService,
    IntradayQueryService,
    ensure_fixture_catalog,
    fixture_rows,
)
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.intraday_provider import FixtureIntradayMarketDataProvider
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.intraday import INTRADAY_TIMEFRAMES
from alphadesk_domain.market_reference import PriceAdjustmentMode
from tests.helpers import require_m03_test_database_url


def integration_settings() -> Settings:
    url = require_m03_test_database_url()
    return Settings(
        environment="test",
        postgres_host=str(url.host),
        postgres_port=url.port or 5432,
        postgres_db=str(url.database),
        postgres_user=str(url.username),
        postgres_password=str(url.password),
        redis_host="unused",
    )


@pytest.mark.integration
@pytest.mark.d03
async def test_fixture_import_aggregation_idempotency_and_bounded_query() -> None:
    database = DatabaseService(integration_settings())
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    try:
        _, instruments = await ensure_fixture_catalog(factory)
        service = IntradayMarketDataImportService(factory, batch_size=500)
        first = await service.run(
            FixtureIntradayMarketDataProvider(fixture_rows()),
            source_code="D03_FIXTURE",
            source_timezone="Asia/Shanghai",
            target_timeframes=INTRADAY_TIMEFRAMES[1:],
            correlation_id=uuid4(),
        )
        assert first.rows_read == 2_639
        assert first.rows_invalid == 0
        assert first.conflicts == 0
        second = await service.run(
            FixtureIntradayMarketDataProvider(fixture_rows()),
            source_code="D03_FIXTURE",
            source_timezone="Asia/Shanghai",
            target_timeframes=INTRADAY_TIMEFRAMES[1:],
            correlation_id=uuid4(),
        )
        assert second.bars_inserted == 0
        assert second.bars_skipped == 2_639
        coverage = await IntradayOverviewService(factory).coverage()
        counts = {item["timeframe"]: item["bar_count"] for item in coverage}
        assert counts["MINUTE_1"] >= 2_400
        assert counts["MINUTE_5"] >= 480
        assert counts["MINUTE_15"] >= 160
        assert counts["MINUTE_30"] >= 80
        assert counts["MINUTE_60"] >= 40
        bars = await IntradayQueryService(factory).bars(
            instrument_id=instruments[0].id,
            source_code="D03_FIXTURE",
            timeframe=MarketTimeframe.MINUTE_5,
            start_at=datetime.fromisoformat("2026-07-06T09:30:00+08:00"),
            end_at=datetime.fromisoformat("2026-07-06T15:00:00+08:00"),
            adjustment_mode=PriceAdjustmentMode.RAW,
            limit=100,
        )
        assert len(bars) == 48
        assert bars == sorted(bars, key=lambda item: item.bar_time)
        async with factory() as uow:
            streamed = [
                item
                async for item in uow.historical_bars.stream_bars(
                    instrument_ids=(instruments[0].id,),
                    timeframe=MarketTimeframe.MINUTE_5,
                    start_at=datetime.fromisoformat("2026-07-06T09:30:00+08:00"),
                    end_at=datetime.fromisoformat("2026-07-06T15:00:00+08:00"),
                    price_adjustment_mode=PriceAdjustmentMode.RAW,
                    batch_size=7,
                )
            ]
        assert len(streamed) == 48
        assert streamed == sorted(streamed, key=lambda item: item.timestamp)
    finally:
        await database.close()
