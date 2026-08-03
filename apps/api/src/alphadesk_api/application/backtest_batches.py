"""Durable independent backtest batches for watchlists and the full A-share market."""

# ruff: noqa: RUF001

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import mean, median
from typing import Any
from uuid import UUID, uuid4

from alphadesk_api.application.backtests import BackfillEnqueuer
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.research_backtests import (
    QuickBacktestRequest,
    QuickBacktestService,
)
from alphadesk_api.application.screenings import PointInTimeAshareUniverseService
from alphadesk_api.core.config import Settings
from alphadesk_domain.backtest import BacktestExecutionPriceMode
from alphadesk_domain.backtest_batches import (
    BacktestBatch,
    BacktestBatchItem,
    BacktestBatchItemStatus,
    BacktestBatchResultRow,
    BacktestBatchScope,
)
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe, TimeInForce
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.scanners import is_st_instrument
from alphadesk_domain.screening import UniverseSpec
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_spec import (
    StrategySpec,
    strategy_spec_from_dict,
    strategy_spec_to_dict,
)
from alphadesk_domain.values import utc_now


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateBacktestBatchRequest:
    scope: BacktestBatchScope
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    spec: StrategySpec | None = None
    user_strategy_id: UUID | None = None
    watchlist_id: UUID | None = None
    exclude_st: bool = True
    exclude_bse: bool = False
    exclude_star_market: bool = False
    exclude_chinext: bool = False
    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = Decimal("5")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    slippage_basis_points: Decimal = Decimal("2")
    maximum_volume_participation: Decimal | None = Decimal("0.1")
    execution_price_mode: BacktestExecutionPriceMode = BacktestExecutionPriceMode.NEXT_OPEN
    signal_timeframe: MarketTimeframe = MarketTimeframe.MINUTE_1
    auto_prepare_minute_data: bool = True
    optimistic_fill_assumption: bool = False
    position_size_ratio: Decimal | None = Decimal("1")
    maximum_entry_gap_ratio: Decimal | None = Decimal("0.05")
    time_in_force: TimeInForce = TimeInForce.DAY
    idempotency_key: str = ""
    correlation_id: UUID | None = None


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _batch_response(batch: BacktestBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "name": batch.name,
        "scope": batch.scope.value,
        "watchlist_id": batch.watchlist_id,
        "status": batch.status.value,
        "total_count": batch.total_count,
        "pending_count": batch.pending_count,
        "running_count": batch.running_count,
        "completed_count": batch.completed_count,
        "failed_count": batch.failed_count,
        "cancelled_count": batch.cancelled_count,
        "progress_percent": batch.progress_percent,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "error_code": batch.error_code,
        "error_message": batch.error_message,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
    }


class BacktestBatchService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._settings = settings

    async def create(self, request: CreateBacktestBatchRequest) -> dict[str, Any]:
        if not request.idempotency_key.strip():
            raise ApplicationError("BACKTEST_BATCH_INVALID", "批量回测缺少幂等键")
        resolver = QuickBacktestService(
            self._uow_factory,
            self._registry,
            self._settings,
        )
        spec, user_strategy_id, version_id = await resolver._resolve_spec(
            QuickBacktestRequest(
                instrument_id=uuid4(),
                start_at=request.start_at,
                end_at=request.end_at,
                initial_cash=request.initial_cash,
                spec=request.spec,
                user_strategy_id=request.user_strategy_id,
            )
        )
        instruments = await self._resolve_instruments(request)
        if not instruments:
            raise ApplicationError(
                "BACKTEST_BATCH_EMPTY_UNIVERSE",
                "所选范围没有可回测的股票",
            )
        if len(instruments) > self._settings.backtest_batch_max_instruments:
            raise ApplicationError(
                "BACKTEST_BATCH_TOO_LARGE",
                f"批量回测最多支持 {self._settings.backtest_batch_max_instruments} 只股票",
            )
        configuration = {
            "schema_version": 1,
            "spec": strategy_spec_to_dict(spec),
            "user_strategy_id": (None if user_strategy_id is None else str(user_strategy_id)),
            "user_strategy_version_id": (None if version_id is None else str(version_id)),
            "start_at": request.start_at.isoformat(),
            "end_at": request.end_at.isoformat(),
            "initial_cash": format(request.initial_cash, "f"),
            "commission_rate": format(request.commission_rate, "f"),
            "minimum_commission": format(request.minimum_commission, "f"),
            "stamp_duty_rate": format(request.stamp_duty_rate, "f"),
            "transfer_fee_rate": format(request.transfer_fee_rate, "f"),
            "slippage_basis_points": format(request.slippage_basis_points, "f"),
            "maximum_volume_participation": (
                None
                if request.maximum_volume_participation is None
                else format(request.maximum_volume_participation, "f")
            ),
            "execution_price_mode": request.execution_price_mode.value,
            "signal_timeframe": request.signal_timeframe.value,
            "auto_prepare_minute_data": request.auto_prepare_minute_data,
            "optimistic_fill_assumption": request.optimistic_fill_assumption,
            "position_size_ratio": (
                None
                if request.position_size_ratio is None
                else format(request.position_size_ratio, "f")
            ),
            "maximum_entry_gap_ratio": (
                None
                if request.maximum_entry_gap_ratio is None
                else format(request.maximum_entry_gap_ratio, "f")
            ),
            "time_in_force": request.time_in_force.value,
            "price_adjustment_mode": PriceAdjustmentMode.RAW.value,
            "filters": {
                "exclude_st": request.exclude_st,
                "exclude_bse": request.exclude_bse,
                "exclude_star_market": request.exclude_star_market,
                "exclude_chinext": request.exclude_chinext,
            },
            "instrument_ids": [str(item.id) for item in instruments],
        }
        fingerprint = _fingerprint(
            {
                "scope": request.scope.value,
                "watchlist_id": (
                    None if request.watchlist_id is None else str(request.watchlist_id)
                ),
                "configuration": configuration,
            }
        )
        async with self._uow_factory() as uow:
            await uow.backtest_batches.lock_idempotency_key(request.idempotency_key)
            existing = await uow.backtest_batches.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "BACKTEST_BATCH_IDEMPOTENCY_CONFLICT",
                        "相同幂等键已用于不同的批量回测条件",
                    )
                return _batch_response(existing)
            batch = BacktestBatch(
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                scope=request.scope,
                name=(
                    "自选组合独立回测"
                    if request.scope is BacktestBatchScope.WATCHLIST
                    else "全A股批量独立回测"
                ),
                configuration=configuration,
                watchlist_id=request.watchlist_id,
                total_count=len(instruments),
                pending_count=len(instruments),
                correlation_id=request.correlation_id or uuid4(),
            )
            await uow.backtest_batches.add(batch)
            await uow.backtest_batches.add_items(
                [
                    BacktestBatchItem(
                        batch_id=batch.id,
                        instrument_id=instrument.id,
                        ordinal=ordinal,
                    )
                    for ordinal, instrument in enumerate(instruments)
                ]
            )
            await uow.commit()
        return _batch_response(batch)

    async def cancel(self, batch_id: UUID) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            batch = await uow.backtest_batches.cancel(batch_id, occurred_at=utc_now())
            if batch is None:
                raise ApplicationError(
                    "BACKTEST_BATCH_NOT_FOUND", "没有找到该批量回测任务"
                )
            await uow.commit()
        return _batch_response(batch)

    async def retry_failed(self, batch_id: UUID) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            existing = await uow.backtest_batches.get_by_id(batch_id)
            if existing is None:
                raise ApplicationError(
                    "BACKTEST_BATCH_NOT_FOUND", "没有找到该批量回测任务"
                )
            if existing.failed_count + existing.cancelled_count == 0:
                raise ApplicationError(
                    "BACKTEST_BATCH_NOT_RETRYABLE", "当前任务没有失败或已取消的股票"
                )
            batch = await uow.backtest_batches.retry_failed(
                batch_id, occurred_at=utc_now()
            )
            assert batch is not None
            await uow.commit()
        return _batch_response(batch)

    async def _resolve_instruments(self, request: CreateBacktestBatchRequest) -> list[Instrument]:
        if request.scope is BacktestBatchScope.WATCHLIST:
            if request.watchlist_id is None:
                raise ApplicationError(
                    "BACKTEST_BATCH_WATCHLIST_REQUIRED",
                    "请选择一个自选列表",
                )
            async with self._uow_factory() as uow:
                watchlist = await uow.watchlists.get_by_id(request.watchlist_id)
                if watchlist is None:
                    raise ApplicationError("WATCHLIST_NOT_FOUND", "没有找到所选自选列表")
                items = await uow.watchlists.list_items(request.watchlist_id)
                instruments = await uow.instruments.get_many([item.instrument_id for item in items])
            by_id = {item.id: item for item in instruments if item.is_active}
            return [
                by_id[item.instrument_id]
                for item in items
                if item.instrument_id in by_id
                and self._included_by_filters(by_id[item.instrument_id], request)
            ]
        as_of_date = (request.end_at - timedelta(microseconds=1)).date()
        resolution = await PointInTimeAshareUniverseService(
            self._uow_factory,
            source_code=self._settings.authoritative_market_source,
        ).resolve(
            as_of_date,
            UniverseSpec(
                exclude_st=request.exclude_st,
                exclude_bse=request.exclude_bse,
                exclude_star_market=request.exclude_star_market,
                exclude_chinext=request.exclude_chinext,
            ),
        )
        return list(resolution.included)

    @staticmethod
    def _included_by_filters(
        instrument: Instrument,
        request: CreateBacktestBatchRequest,
    ) -> bool:
        if request.exclude_st and is_st_instrument(instrument):
            return False
        if request.exclude_bse and instrument.exchange == "BSE":
            return False
        if request.exclude_star_market and instrument.symbol.startswith(("688", "689")):
            return False
        return not (request.exclude_chinext and instrument.symbol.startswith(("300", "301")))


class BacktestBatchProcessor:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        settings: Settings,
        enqueue_backfill: BackfillEnqueuer | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._quick = QuickBacktestService(
            uow_factory,
            registry,
            settings,
            enqueue_backfill,
        )
        self._settings = settings

    async def process_next(self) -> UUID | None:
        async with self._uow_factory() as uow:
            claimed = await uow.backtest_batches.claim_next(
                stale_before=utc_now()
                - timedelta(seconds=self._settings.backtest_batch_item_stale_seconds)
            )
            if claimed is None:
                return None
            batch, item = claimed
            await uow.commit()
        payload = batch.configuration
        try:
            result = await self._quick.run(
                QuickBacktestRequest(
                    instrument_id=item.instrument_id,
                    start_at=_parse_datetime(payload["start_at"]),
                    end_at=_parse_datetime(payload["end_at"]),
                    initial_cash=Decimal(str(payload["initial_cash"])),
                    spec=strategy_spec_from_dict(payload["spec"]),
                    commission_rate=Decimal(str(payload["commission_rate"])),
                    minimum_commission=Decimal(str(payload["minimum_commission"])),
                    stamp_duty_rate=Decimal(str(payload["stamp_duty_rate"])),
                    transfer_fee_rate=Decimal(str(payload["transfer_fee_rate"])),
                    slippage_basis_points=Decimal(str(payload["slippage_basis_points"])),
                    maximum_volume_participation=_optional_decimal(
                        payload.get("maximum_volume_participation")
                    ),
                    execution_price_mode=BacktestExecutionPriceMode(
                        str(payload["execution_price_mode"])
                    ),
                    signal_timeframe=MarketTimeframe(
                        str(payload.get("signal_timeframe", MarketTimeframe.MINUTE_1.value))
                    ),
                    auto_prepare_minute_data=bool(
                        payload.get("auto_prepare_minute_data", True)
                    ),
                    optimistic_fill_assumption=bool(
                        payload.get("optimistic_fill_assumption", False)
                    ),
                    position_size_ratio=_optional_decimal(payload.get("position_size_ratio")),
                    maximum_entry_gap_ratio=_optional_decimal(
                        payload.get("maximum_entry_gap_ratio")
                    ),
                    time_in_force=TimeInForce(str(payload["time_in_force"])),
                    idempotency_key=(
                        f"batch:{batch.id}:{item.instrument_id}:attempt:{item.attempt_count}"
                    ),
                    correlation_id=batch.correlation_id,
                )
            )
            item.backtest_run_id = UUID(str(result["id"]))
            result_status = str(result.get("status", ""))
            error_code = str(result.get("error_code") or "")
            error_message = str(result.get("error_message") or "")
            if (
                result_status == "FAILED"
                and error_code
                in {
                    "BACKTEST_DAILY_DATA_PREPARING",
                    "BACKTEST_MINUTE_DATA_PREPARING",
                }
                and bool(payload.get("auto_prepare_minute_data", True))
                and item.attempt_count < self._settings.backtest_batch_data_max_attempts
            ):
                item.status = BacktestBatchItemStatus.PENDING
                item.error_code = error_code
                item.error_message = error_message[:512]
                item.completed_at = None
                item.updated_at = utc_now() + timedelta(
                    seconds=self._settings.backtest_batch_data_retry_seconds
                )
            elif result_status == "FAILED":
                item.status = BacktestBatchItemStatus.FAILED
                item.error_code = error_code or "BACKTEST_BATCH_ITEM_FAILED"
                item.error_message = error_message[:512] or "单股回测执行失败"
                item.completed_at = utc_now()
                item.updated_at = item.completed_at
            else:
                item.status = BacktestBatchItemStatus.COMPLETED
                item.error_code = None
                item.error_message = None
                item.completed_at = utc_now()
                item.updated_at = item.completed_at
        except ApplicationError as exc:
            item.status = BacktestBatchItemStatus.FAILED
            item.error_code = exc.code
            item.error_message = str(exc)[:512]
            item.completed_at = utc_now()
            item.updated_at = item.completed_at
        except Exception as exc:  # one stock must never stop the whole batch
            item.status = BacktestBatchItemStatus.FAILED
            item.error_code = "BACKTEST_BATCH_ITEM_FAILED"
            item.error_message = str(exc)[:512]
            item.completed_at = utc_now()
            item.updated_at = item.completed_at
        async with self._uow_factory() as uow:
            await uow.backtest_batches.finish_item(item)
            await uow.commit()
        return batch.id


class BacktestBatchQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list(self, *, page: int, page_size: int) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            items, total = await uow.backtest_batches.list(
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return {
            "items": [_batch_response(item) for item in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def detail(self, batch_id: UUID) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            batch = await uow.backtest_batches.get_by_id(batch_id)
        if batch is None:
            raise ApplicationError("BACKTEST_BATCH_NOT_FOUND", "没有找到该批量回测任务")
        result = _batch_response(batch)
        result["filters"] = batch.configuration.get("filters", {})
        return result

    async def results(self, batch_id: UUID, *, page: int, page_size: int) -> dict[str, Any]:
        await self.detail(batch_id)
        async with self._uow_factory() as uow:
            rows, total = await uow.backtest_batches.list_results(
                batch_id,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return {
            "items": [
                {
                    **asdict(row),
                    "status": row.status.value,
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def summary(self, batch_id: UUID) -> dict[str, Any]:
        batch = await self.detail(batch_id)
        async with self._uow_factory() as uow:
            rows = await uow.backtest_batches.list_all_results(batch_id)

        completed = [row for row in rows if row.status is BacktestBatchItemStatus.COMPLETED]
        traded = [row for row in completed if (row.fill_count or 0) > 0]
        returns = [_number(row.total_return) for row in completed if row.total_return is not None]
        drawdowns = [
            _number(row.maximum_drawdown) for row in completed if row.maximum_drawdown is not None
        ]
        sharpes = [_number(row.sharpe_ratio) for row in completed if row.sharpe_ratio is not None]
        profitable = [value for value in returns if value > 0]
        ordered = sorted(
            (row for row in completed if row.total_return is not None),
            key=lambda row: _number(row.total_return),
            reverse=True,
        )
        failures: dict[str, int] = {}
        for row in rows:
            if row.status is BacktestBatchItemStatus.FAILED:
                label = row.error_code or "未分类失败"
                failures[label] = failures.get(label, 0) + 1

        return {
            "batch": batch,
            "notice": (
                "本报告汇总的是逐股独立回测样本；每只股票使用独立初始资金，"
                "不共享现金与持仓，因此不是组合资金曲线，也不代表组合收益。"
            ),
            "counts": {
                "total": len(rows),
                "completed": len(completed),
                "failed": sum(row.status is BacktestBatchItemStatus.FAILED for row in rows),
                "traded": len(traded),
                "profitable": len(profitable),
            },
            "ratios": {
                "traded": _ratio(len(traded), len(completed)),
                "profitable": _ratio(len(profitable), len(completed)),
            },
            "returns": _distribution(returns),
            "drawdowns": _distribution(drawdowns),
            "sharpe_distribution": _histogram([float(value) for value in sharpes], 8),
            "fill_distribution": _histogram([float(row.fill_count or 0) for row in completed], 8),
            "return_histogram": _histogram([float(value) for value in returns], 10),
            "return_drawdown_scatter": [
                {
                    "instrument_id": str(row.instrument_id),
                    "instrument_display": f"{row.name}（{row.symbol}.{row.exchange}）",
                    "total_return": row.total_return,
                    "maximum_drawdown": row.maximum_drawdown,
                }
                for row in completed
                if row.total_return is not None and row.maximum_drawdown is not None
            ],
            "top": [_row_payload(row) for row in ordered[:10]],
            "bottom": [_row_payload(row) for row in reversed(ordered[-10:])],
            "failure_reasons": [
                {"code": code, "count": count}
                for code, count in sorted(failures.items(), key=lambda item: (-item[1], item[0]))
            ],
            "intraday_execution": {
                "daily_bars_checked": sum(row.bars_processed or 0 for row in completed),
                "daily_prefilter_candidates": sum(
                    row.candidate_session_count or 0 for row in completed
                ),
                "daily_prefilter_excluded": sum(
                    int((row.data_preparation_summary or {}).get(
                        "prefilter_excluded_session_count", 0
                    ))
                    for row in completed
                ),
                "minute_sessions_loaded": sum(
                    row.minute_replay_session_count or 0 for row in completed
                ),
                "minute_bars_processed": sum(
                    row.processed_minute_bar_count or 0 for row in completed
                ),
                "signals_generated": sum(row.signals_generated or 0 for row in completed),
                "stocks_with_signals": sum(
                    (row.signals_generated or 0) > 0 for row in completed
                ),
                "stocks_with_fills": len(traded),
                "data_preparation_seconds": sum(
                    float((row.performance_summary or {}).get(
                        "data_preparation_seconds", 0
                    ))
                    for row in completed
                ),
                "strategy_replay_seconds": sum(
                    float((row.performance_summary or {}).get(
                        "strategy_replay_seconds", 0
                    ))
                    for row in completed
                ),
            },
        }

    async def csv(self, batch_id: UUID) -> str:
        await self.detail(batch_id)
        async with self._uow_factory() as uow:
            rows = await uow.backtest_batches.list_all_results(batch_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "股票名称",
                "股票代码",
                "状态",
                "总收益率",
                "年化收益率",
                "最大回撤",
                "夏普比率",
                "成交数",
                "失败代码",
                "失败原因",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    f"{row.symbol}.{row.exchange}",
                    row.status.value,
                    row.total_return or "",
                    row.annualized_return or "",
                    row.maximum_drawdown or "",
                    row.sharpe_ratio or "",
                    "" if row.fill_count is None else row.fill_count,
                    row.error_code or "",
                    row.error_message or "",
                ]
            )
        return "\ufeff" + output.getvalue()


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _parse_datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _number(value: object) -> Decimal:
    return Decimal(str(value))


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return _decimal_text(Decimal(numerator) / Decimal(denominator))


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = percentile * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _distribution(values: list[Decimal]) -> dict[str, str | int | None]:
    if not values:
        return {
            "count": 0,
            "average": None,
            "median": None,
            "p25": None,
            "p50": None,
            "p75": None,
        }
    return {
        "count": len(values),
        "average": _decimal_text(mean(values)),
        "median": _decimal_text(median(values)),
        "p25": _decimal_text(_percentile(values, Decimal("0.25"))),
        "p50": _decimal_text(_percentile(values, Decimal("0.50"))),
        "p75": _decimal_text(_percentile(values, Decimal("0.75"))),
    }


def _histogram(values: list[float], bucket_count: int) -> list[dict[str, float | int]]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return [{"minimum": minimum, "maximum": maximum, "count": len(values)}]
    width = (maximum - minimum) / bucket_count
    counts = [0] * bucket_count
    for value in values:
        index = min(bucket_count - 1, int((value - minimum) / width))
        counts[index] += 1
    return [
        {
            "minimum": minimum + width * index,
            "maximum": minimum + width * (index + 1),
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


def _row_payload(row: BacktestBatchResultRow) -> dict[str, Any]:
    return {
        **asdict(row),
        "status": row.status.value,
        "instrument_display": f"{row.name}（{row.symbol}.{row.exchange}）",
    }
