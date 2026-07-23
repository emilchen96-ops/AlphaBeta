"""Pure domain contracts for the MiniQMT read-only market-data gateway."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from alphadesk_domain.values import as_utc, decimal_value, non_empty


class MiniQMTTradingDisabledError(RuntimeError):
    """Raised for every attempted trading command at the agent boundary."""

    code = "MINIQMT_TRADING_DISABLED"

    def __init__(self) -> None:
        super().__init__("MiniQMT交易功能未启用; 当前代理仅允许读取行情。")


class SubscriptionOrigin(StrEnum):
    WATCHLIST = "WATCHLIST"
    SCANNER = "SCANNER"
    BENCHMARK = "BENCHMARK"
    TEMPORARY = "TEMPORARY"


class SubscriptionState(StrEnum):
    WAITING = "WAITING"
    SUBSCRIBED = "SUBSCRIBED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    REJECTED = "REJECTED"


class TradingStatus(StrEnum):
    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"
    HALTED = "HALTED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


def miniqmt_provider_symbol(symbol: str, exchange: str) -> str:
    suffix = {
        "SSE": "SH",
        "SHSE": "SH",
        "SZSE": "SZ",
        "BSE": "BJ",
        "BJSE": "BJ",
    }.get(exchange.upper())
    if suffix is None:
        raise ValueError(f"unsupported exchange: {exchange}")
    return f"{symbol}.{suffix}"


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteSnapshot:
    instrument_id: UUID
    symbol: str
    exchange: str
    market_time: datetime
    received_at: datetime
    ingested_at: datetime
    last_price: Decimal
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    previous_close: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    bid_price_1: Decimal | None = None
    ask_price_1: Decimal | None = None
    bid_volume_1: Decimal | None = None
    ask_volume_1: Decimal | None = None
    upper_limit_price: Decimal | None = None
    lower_limit_price: Decimal | None = None
    trading_status: TradingStatus = TradingStatus.UNKNOWN
    source: str = "MINIQMT"
    source_sequence: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", non_empty(self.symbol, "symbol"))
        object.__setattr__(self, "exchange", non_empty(self.exchange, "exchange").upper())
        object.__setattr__(self, "source", non_empty(self.source, "source").upper())
        for name in ("market_time", "received_at", "ingested_at"):
            object.__setattr__(self, name, as_utc(getattr(self, name), name))
        for name in (
            "last_price",
            "open_price",
            "high_price",
            "low_price",
            "previous_close",
            "bid_price_1",
            "ask_price_1",
            "upper_limit_price",
            "lower_limit_price",
        ):
            value = getattr(self, name)
            if value is not None:
                decimal_value(value, name)
                if value <= 0:
                    raise ValueError(f"{name} must be positive")
        for name in ("volume", "amount", "bid_volume_1", "ask_volume_1"):
            value = getattr(self, name)
            if value is not None:
                decimal_value(value, name)
                if value < 0:
                    raise ValueError(f"{name} must be non-negative")
        if self.schema_version != 1:
            raise ValueError("unsupported quote schema_version")

    @property
    def deduplication_key(self) -> tuple[UUID, datetime, str | None]:
        return self.instrument_id, self.market_time, self.source_sequence


@dataclass(frozen=True, slots=True, kw_only=True)
class DesiredSubscription:
    instrument_id: UUID
    symbol: str
    exchange: str
    name: str
    origins: tuple[SubscriptionOrigin, ...]

    @property
    def provider_symbol(self) -> str:
        return miniqmt_provider_symbol(self.symbol, self.exchange)


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionPlan:
    desired_instruments: tuple[DesiredSubscription, ...]
    current_instrument_ids: tuple[UUID, ...]
    instruments_to_subscribe: tuple[DesiredSubscription, ...]
    instruments_to_unsubscribe: tuple[UUID, ...]
    rejected_instruments: tuple[tuple[DesiredSubscription, str], ...]
    plan_version: str


class MarketSubscriptionPlanService:
    """Deterministically merge subscription sources and calculate a diff."""

    def build(
        self,
        *,
        candidates: tuple[DesiredSubscription, ...],
        current_instrument_ids: tuple[UUID, ...],
        max_subscriptions: int,
        plan_version: str,
    ) -> SubscriptionPlan:
        if max_subscriptions < 1:
            raise ValueError("max_subscriptions must be positive")
        merged: dict[UUID, DesiredSubscription] = {}
        for item in candidates:
            previous = merged.get(item.instrument_id)
            origins = set(item.origins)
            if previous is not None:
                origins.update(previous.origins)
            merged[item.instrument_id] = DesiredSubscription(
                instrument_id=item.instrument_id,
                symbol=item.symbol,
                exchange=item.exchange,
                name=item.name,
                origins=tuple(sorted(origins, key=str)),
            )
        ordered = tuple(
            sorted(
                merged.values(),
                key=lambda item: (
                    min(
                        (
                            SubscriptionOrigin.BENCHMARK,
                            SubscriptionOrigin.WATCHLIST,
                            SubscriptionOrigin.SCANNER,
                            SubscriptionOrigin.TEMPORARY,
                        ).index(origin)
                        for origin in item.origins
                    ),
                    item.exchange,
                    item.symbol,
                    str(item.instrument_id),
                ),
            )
        )
        supported: list[DesiredSubscription] = []
        unsupported: list[tuple[DesiredSubscription, str]] = []
        for item in ordered:
            try:
                miniqmt_provider_symbol(item.symbol, item.exchange)
            except ValueError:
                unsupported.append((item, "UNSUPPORTED_EXCHANGE"))
            else:
                supported.append(item)
        desired = tuple(supported[:max_subscriptions])
        rejected = tuple(unsupported) + tuple(
            (item, "SUBSCRIPTION_LIMIT_EXCEEDED") for item in supported[max_subscriptions:]
        )
        desired_ids = {item.instrument_id for item in desired}
        current_ids = set(current_instrument_ids)
        return SubscriptionPlan(
            desired_instruments=desired,
            current_instrument_ids=tuple(sorted(current_ids, key=str)),
            instruments_to_subscribe=tuple(
                item for item in desired if item.instrument_id not in current_ids
            ),
            instruments_to_unsubscribe=tuple(sorted(current_ids - desired_ids, key=str)),
            rejected_instruments=rejected,
            plan_version=non_empty(plan_version, "plan_version"),
        )


class RealtimeMarketDataProvider(Protocol):
    @property
    def connected(self) -> bool: ...

    def connect(self) -> None: ...

    def latest_raw_snapshot(self, provider_symbol: str) -> dict[str, object] | None: ...

    def normalize_quote(self, raw: dict[str, object]) -> dict[str, object]: ...


class MarketSubscriptionProvider(Protocol):
    def subscribe_quote(
        self,
        provider_symbol: str,
        callback: Callable[[str, dict[str, object]], None],
        *,
        period: str = "tick",
    ) -> int: ...

    def unsubscribe(self, subscription_id: int) -> None: ...


class HistoricalIntradayDataProvider(Protocol):
    def history(
        self,
        provider_symbols: tuple[str, ...],
        *,
        period: str,
        start_time: str,
        end_time: str,
    ) -> list[dict[str, object]]: ...


@dataclass(slots=True)
class ActiveSubscriptionRegistry:
    """Recoverable in-process mirror; PostgreSQL remains the reported fact store."""

    by_instrument: dict[UUID, int] = field(default_factory=dict)

    def replace(self, values: dict[UUID, int]) -> None:
        self.by_instrument = dict(values)
