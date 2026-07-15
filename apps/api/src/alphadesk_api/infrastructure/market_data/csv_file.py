"""Bounded local CSV adapter used for explicit offline imports."""

import csv
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe
from alphadesk_domain.market_adapters import (
    ExternalInstrument,
    ExternalMarketBar,
    MarketDataAdapterRangeError,
    MarketDataHealth,
)

REQUIRED_COLUMNS = {"symbol", "bar_time", "open", "high", "low", "close", "volume"}


class LocalCsvMarketDataAdapter:
    """Read a user-selected local file with strict size, row, and schema limits."""

    def __init__(
        self,
        path: Path,
        *,
        source_code: str,
        timeframe: MarketTimeframe,
        max_bytes: int,
        max_rows: int,
    ) -> None:
        raw_path = str(path)
        normalized_path = raw_path.lower().replace("\\", "/")
        if normalized_path.startswith(("http:/", "https:/")):
            raise ValueError("remote CSV URLs are not allowed")
        self._path = path.expanduser().resolve(strict=True)
        if not self._path.is_file():
            raise ValueError("CSV path must be a regular file")
        if self._path.stat().st_size > max_bytes:
            raise ValueError("CSV file exceeds the configured byte limit")
        self.source_code = source_code.strip().upper()
        if not self.source_code:
            raise ValueError("source_code is required")
        self._timeframe = timeframe
        self._rows = self._read_rows(max_rows)

    @property
    def symbols(self) -> list[str]:
        return sorted({row["symbol"].strip() for row in self._rows})

    def _read_rows(self, max_rows: int) -> list[dict[str, str]]:
        with self._path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = set(reader.fieldnames or ())
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
            rows: list[dict[str, str]] = []
            for index, row in enumerate(reader, start=1):
                if index > max_rows:
                    raise ValueError("CSV file exceeds the configured row limit")
                rows.append({key: value or "" for key, value in row.items()})
        return rows

    async def health_check(self) -> MarketDataHealth:
        return MarketDataHealth(
            status=MarketDataSourceStatus.ACTIVE,
            checked_at=datetime.now(UTC),
            message="bounded local CSV source",
        )

    async def list_instruments(
        self,
        exchange: str | None = None,
        market: str | None = None,
    ) -> list[ExternalInstrument]:
        del exchange, market
        return []

    async def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]:
        del adjustment
        if start.tzinfo is None or end.tzinfo is None:
            raise MarketDataAdapterRangeError("start and end must be timezone-aware")
        requested = set(symbols)
        for row in self._rows:
            if row["symbol"].strip() not in requested:
                continue
            if timeframe is not self._timeframe:
                continue
            bar_time = datetime.fromisoformat(row["bar_time"].strip()).astimezone(UTC)
            if start <= bar_time <= end:
                source_updated = row.get("source_updated_at", "").strip()
                yield ExternalMarketBar(
                    symbol=row["symbol"].strip(),
                    timeframe=timeframe,
                    bar_time=bar_time,
                    open=row["open"].strip(),
                    high=row["high"].strip(),
                    low=row["low"].strip(),
                    close=row["close"].strip(),
                    volume=row["volume"].strip(),
                    amount=row.get("amount", "").strip() or None,
                    vwap=row.get("vwap", "").strip() or None,
                    open_interest=row.get("open_interest", "").strip() or None,
                    source_updated_at=(
                        datetime.fromisoformat(source_updated).astimezone(UTC)
                        if source_updated
                        else None
                    ),
                )
