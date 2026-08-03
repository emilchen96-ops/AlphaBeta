"""Deterministic BT02-A layered-loading benchmark.

The benchmark does not download market data.  It measures the actual domain
prefilter and minute replay code on a reproducible two-year A-share-shaped
sample, then records a transparent full-market extrapolation.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from alphadesk_domain.backtest import ASHARE_TIMEZONE  # noqa: E402
from alphadesk_domain.enums import MarketTimeframe, OrderSide  # noqa: E402
from alphadesk_domain.intraday_backtest import (  # noqa: E402
    IntradayDailyStrategyEvaluator,
    PriceVolumeSmaRule,
    build_partial_daily_bar,
    safe_prefilter_plan,
)
from alphadesk_domain.market_reference import PriceAdjustmentMode  # noqa: E402
from alphadesk_domain.strategy import StrategyBar  # noqa: E402

TRADING_SESSIONS = 504
MINUTES_PER_SESSION = 240
FULL_MARKET_STOCKS = 5536
RULE = PriceVolumeSmaRule(10, 10, Decimal("1.2"), 5, Decimal("100"))


def _trading_days(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _at(day: date, value: time) -> datetime:
    return datetime.combine(day, value, ASHARE_TIMEZONE).astimezone(UTC)


def _daily_bars(instrument_id: UUID) -> list[StrategyBar]:
    days = _trading_days(date(2024, 1, 2), TRADING_SESSIONS)
    rows: list[StrategyBar] = []
    for index, day in enumerate(days):
        close = Decimal("10")
        high = Decimal("10")
        low = Decimal("10")
        volume = Decimal("100")
        if index == TRADING_SESSIONS - 9:
            close, high, volume = Decimal("11"), Decimal("11"), Decimal("130")
        elif index > TRADING_SESSIONS - 9:
            close, low = Decimal("9.8"), Decimal("9.8")
        rows.append(
            StrategyBar(
                instrument_id=instrument_id,
                symbol=f"{instrument_id.int % 1_000_000:06d}",
                exchange="SZSE",
                timeframe=MarketTimeframe.DAY_1,
                timestamp=_at(day, time(15, 0)),
                open=Decimal("10"),
                high=high,
                low=low,
                close=close,
                volume=volume,
                amount=close * volume,
                adjustment_mode=PriceAdjustmentMode.RAW,
                raw_reference_price=close,
            )
        )
    return rows


def _minute_session(daily: StrategyBar) -> list[StrategyBar]:
    day = daily.timestamp.astimezone(ASHARE_TIMEZONE).date()
    starts: list[time] = []
    cursor = datetime.combine(day, time(9, 30))
    while cursor.time() < time(11, 30):
        starts.append(cursor.time())
        cursor += timedelta(minutes=1)
    cursor = datetime.combine(day, time(13, 0))
    while cursor.time() < time(15, 0):
        starts.append(cursor.time())
        cursor += timedelta(minutes=1)
    per_bar_volume = daily.volume / Decimal(len(starts))
    return [
        StrategyBar(
            instrument_id=daily.instrument_id,
            symbol=daily.symbol,
            exchange=daily.exchange,
            timeframe=MarketTimeframe.MINUTE_1,
            timestamp=_at(day, start),
            open=(daily.close if index == len(starts) - 1 else daily.open),
            high=(daily.high if index == len(starts) - 1 else daily.open),
            low=(daily.low if index == len(starts) - 1 else daily.open),
            close=(daily.close if index == len(starts) - 1 else daily.open),
            volume=per_bar_volume,
            amount=per_bar_volume * daily.close,
            adjustment_mode=PriceAdjustmentMode.RAW,
            raw_reference_price=daily.close,
        )
        for index, start in enumerate(starts)
    ]


def _measure(stock_count: int) -> dict[str, int | float]:
    daily_sets = [_daily_bars(UUID(int=index + 1)) for index in range(stock_count)]
    started = perf_counter()
    plans = [safe_prefilter_plan(rows, RULE) for rows in daily_sets]
    preparation_seconds = perf_counter() - started

    started = perf_counter()
    loaded = 0
    signal_count = 0
    for rows, plan in zip(daily_sets, plans, strict=True):
        evaluator = IntradayDailyStrategyEvaluator(
            strategy_key="price_volume_breakout_sma_exit",
            strategy_version="1.0.0",
            rule=RULE,
            spec=None,
        )
        by_date = {
            item.timestamp.astimezone(ASHARE_TIMEZONE).date(): (index, item)
            for index, item in enumerate(rows)
        }
        for trading_date in sorted(plan.replay_dates):
            index, daily = by_date[trading_date]
            minutes = _minute_session(daily)
            loaded += len(minutes)
            for minute_index, minute in enumerate(minutes):
                partial = build_partial_daily_bar(daily, minutes[: minute_index + 1])
                drafts = evaluator.evaluate(
                    completed_daily_bars=rows[:index],
                    partial_daily_bar=partial,
                    generated_at=minute.timestamp + timedelta(minutes=1),
                )
                signal_count += len(drafts)
                for draft in drafts:
                    evaluator.record_fill(
                        daily.instrument_id,
                        draft.side if draft.side is not None else OrderSide.BUY,
                    )
    replay_seconds = perf_counter() - started
    raw = stock_count * TRADING_SESSIONS * MINUTES_PER_SESSION
    return {
        "stocks": stock_count,
        "daily_bars": stock_count * TRADING_SESSIONS,
        "raw_minute_bars": raw,
        "candidate_sessions": sum(len(plan.replay_dates) for plan in plans),
        "loaded_minute_bars": loaded,
        "reduction_ratio": round(1 - (loaded / raw), 6),
        "signals": signal_count,
        "data_preparation_seconds": round(preparation_seconds, 6),
        "strategy_replay_seconds": round(replay_seconds, 6),
        "total_seconds": round(preparation_seconds + replay_seconds, 6),
    }


def main() -> None:
    results = [_measure(count) for count in (1, 10, 100)]
    baseline = results[-1]
    per_stock_seconds = float(baseline["total_seconds"]) / 100
    full_market_candidate_sessions = (
        int(baseline["candidate_sessions"]) // 100 * FULL_MARKET_STOCKS
    )
    full_market_loaded = full_market_candidate_sessions * MINUTES_PER_SESSION
    full_market_raw = FULL_MARKET_STOCKS * TRADING_SESSIONS * MINUTES_PER_SESSION
    payload = {
        "benchmark": "BT02-A deterministic layered-loading benchmark",
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "not reported by operating system",
            "logical_cpu_count": os.cpu_count(),
            "python": platform.python_version(),
        },
        "sample": {
            "sessions_per_stock": TRADING_SESSIONS,
            "minutes_per_session": MINUTES_PER_SESSION,
            "candidate_shape": "one late entry candidate plus full subsequent holding window",
            "data_origin": "deterministic controlled sample; no fixture is presented as live market acceptance",
        },
        "measurements": results,
        "full_a_share_extrapolation": {
            "stocks": FULL_MARKET_STOCKS,
            "raw_minute_bars": full_market_raw,
            "candidate_sessions": full_market_candidate_sessions,
            "loaded_minute_bars": full_market_loaded,
            "reduction_ratio": round(1 - full_market_loaded / full_market_raw, 6),
            "estimated_compute_seconds": round(per_stock_seconds * FULL_MARKET_STOCKS, 3),
            "warning": "Compute-only extrapolation; MiniQMT download latency and real candidate density must be measured online.",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
