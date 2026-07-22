"""Offline-only D03 intraday providers."""

from __future__ import annotations

import csv
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from alphadesk_domain.enums import AdjustmentType, MarketTimeframe
from alphadesk_domain.intraday import (
    INTRADAY_TIMEFRAMES,
    IntradayExternalBar,
    IntradayProviderHealth,
    IntradayProviderStatus,
)

REQUIRED_COLUMNS = {
    "symbol",
    "exchange",
    "timestamp",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "volume",
}
TIMEFRAME_ALIASES = {
    "1M": MarketTimeframe.MINUTE_1,
    "5M": MarketTimeframe.MINUTE_5,
    "15M": MarketTimeframe.MINUTE_15,
    "30M": MarketTimeframe.MINUTE_30,
    "60M": MarketTimeframe.MINUTE_60,
    **{item.value: item for item in INTRADAY_TIMEFRAMES},
}


class FixtureIntradayMarketDataProvider:
    provider_key = "D03_FIXTURE"
    supported_timeframes = (MarketTimeframe.MINUTE_1,)

    def __init__(self, rows: Iterable[IntradayExternalBar]) -> None:
        self._rows = tuple(rows)

    def validate_configuration(self) -> None:
        return None

    async def health_status(self) -> IntradayProviderStatus:
        return IntradayProviderStatus(
            provider_key=self.provider_key,
            health=IntradayProviderHealth.AVAILABLE,
            supported_timeframes=self.supported_timeframes,
            input_types=("fixture",),
            message="deterministic offline D03 fixture",
        )

    async def fetch_bars(self) -> AsyncIterator[IntradayExternalBar]:
        for row in self._rows:
            yield row


class LocalFileIntradayMarketDataProvider:
    provider_key = "LOCAL_FILE"
    supported_timeframes = INTRADAY_TIMEFRAMES

    def __init__(
        self,
        path: Path,
        *,
        source_timezone: str | None,
        max_bytes: int,
        max_rows: int,
        encoding: str = "utf-8-sig",
        delimiter: str = ",",
        allowed_root: Path | None = None,
    ) -> None:
        if str(path).lower().startswith(("http:", "https:")):
            raise ValueError("INTRADAY_FILE_FORMAT_NOT_SUPPORTED")
        self._path = path.expanduser().resolve(strict=True)
        root = allowed_root.expanduser().resolve(strict=True) if allowed_root else self._path.parent
        if self._path != root and root not in self._path.parents:
            raise ValueError("INTRADAY_FILE_NOT_FOUND")
        if not self._path.is_file():
            raise ValueError("INTRADAY_FILE_NOT_FOUND")
        if self._path.suffix.lower() != ".csv":
            raise ValueError("INTRADAY_FILE_FORMAT_NOT_SUPPORTED")
        if self._path.stat().st_size > max_bytes:
            raise ValueError("INTRADAY_FILE_TOO_LARGE")
        if not 1 <= max_rows <= 1_000_000:
            raise ValueError("max_rows is outside the safe range")
        if len(delimiter) != 1:
            raise ValueError("delimiter must be one character")
        self._source_timezone = source_timezone
        self._max_rows = max_rows
        self._encoding = encoding
        self._delimiter = delimiter
        self.validate_configuration()

    def validate_configuration(self) -> None:
        if self._source_timezone is not None:
            ZoneInfo(self._source_timezone)
        with self._path.open("r", encoding=self._encoding, newline="") as stream:
            columns = set(csv.DictReader(stream, delimiter=self._delimiter).fieldnames or ())
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

    async def health_status(self) -> IntradayProviderStatus:
        return IntradayProviderStatus(
            provider_key=self.provider_key,
            health=IntradayProviderHealth.AVAILABLE,
            supported_timeframes=self.supported_timeframes,
            input_types=("csv",),
            message="CSV enabled; Parquet disabled because pyarrow is not installed",
        )

    def _timestamp(self, raw: str) -> datetime:
        parsed = datetime.fromisoformat(raw.strip())
        if parsed.tzinfo is None:
            if self._source_timezone is None:
                raise ValueError("INTRADAY_TIMEZONE_REQUIRED")
            parsed = parsed.replace(tzinfo=ZoneInfo(self._source_timezone))
        return parsed

    async def fetch_bars(self) -> AsyncIterator[IntradayExternalBar]:
        with self._path.open("r", encoding=self._encoding, newline="") as stream:
            reader = csv.DictReader(stream, delimiter=self._delimiter)
            for index, row in enumerate(reader, start=1):
                if index > self._max_rows:
                    raise ValueError("INTRADAY_FILE_TOO_LARGE")
                timeframe = TIMEFRAME_ALIASES.get((row.get("timeframe") or "").strip().upper())
                if timeframe is None:
                    raise ValueError("INTRADAY_TIMEFRAME_NOT_SUPPORTED")
                adjustment = (row.get("adjustment_mode") or "NONE").strip().upper()
                yield IntradayExternalBar(
                    symbol=(row.get("symbol") or "").strip().upper(),
                    exchange=(row.get("exchange") or "").strip().upper(),
                    timestamp=self._timestamp(row.get("timestamp") or ""),
                    timeframe=timeframe,
                    open=(row.get("open") or "").strip(),
                    high=(row.get("high") or "").strip(),
                    low=(row.get("low") or "").strip(),
                    close=(row.get("close") or "").strip(),
                    volume=(row.get("volume") or "").strip(),
                    amount=(row.get("amount") or "").strip() or None,
                    source=(row.get("source") or "").strip() or None,
                    adjustment_mode=AdjustmentType(adjustment),
                    metadata={"input_row": index, "timestamp_semantics": "BAR_START"},
                )


class DisabledExternalIntradayProvider:
    provider_key = "EXTERNAL_INTRADAY_DISABLED"
    supported_timeframes = INTRADAY_TIMEFRAMES

    def validate_configuration(self) -> None:
        raise ValueError("INTRADAY_PROVIDER_NOT_AVAILABLE")

    async def health_status(self) -> IntradayProviderStatus:
        return IntradayProviderStatus(
            provider_key=self.provider_key,
            health=IntradayProviderHealth.DISABLED,
            supported_timeframes=self.supported_timeframes,
            input_types=(),
            message="external intraday provider is intentionally disabled",
        )

    async def fetch_bars(self) -> AsyncIterator[IntradayExternalBar]:
        if False:  # pragma: no cover - keeps this an async generator
            yield cast(IntradayExternalBar, None)
        raise ValueError("INTRADAY_PROVIDER_NOT_AVAILABLE")
