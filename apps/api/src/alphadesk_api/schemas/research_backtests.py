"""UX02 quick-backtest HTTP contracts."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphadesk_domain.backtest import BacktestExecutionPriceMode
from alphadesk_domain.backtest_batches import BacktestBatchExecutionMode
from alphadesk_domain.enums import MarketTimeframe, TimeInForce
from alphadesk_domain.market_reference import PriceAdjustmentMode


class QuickBacktestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: UUID
    start_at: datetime
    end_at: datetime
    initial_cash: str = "100000"
    spec: dict[str, Any] | None = None
    user_strategy_id: UUID | None = None
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW
    commission_rate: str = "0.0003"
    minimum_commission: str | None = "5"
    stamp_duty_rate: str = "0.0005"
    transfer_fee_rate: str = "0.00001"
    slippage_basis_points: str = "2"
    maximum_volume_participation: str | None = "0.1"
    execution_price_mode: BacktestExecutionPriceMode = BacktestExecutionPriceMode.NEXT_OPEN
    signal_timeframe: MarketTimeframe = MarketTimeframe.MINUTE_1
    auto_prepare_minute_data: bool = True
    optimistic_fill_assumption: bool = False
    position_size_ratio: str | None = "1"
    maximum_entry_gap_ratio: str | None = "0.05"
    time_in_force: TimeInForce = TimeInForce.DAY
    idempotency_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def exactly_one_strategy(self) -> Self:
        if (self.spec is None) == (self.user_strategy_id is None):
            raise ValueError("必须且只能提供策略规则或我的策略编号之一")
        if self.start_at >= self.end_at:
            raise ValueError("回测开始时间必须早于结束时间")
        if self.execution_price_mode is BacktestExecutionPriceMode.SIGNAL_CLOSE_LIMIT:
            # The legacy close-limit path continues to use the quantity emitted
            # by the strategy. Position sizing is only meaningful when the
            # execution price is known at the following session open.
            self.position_size_ratio = None
        return self


class ResearchBacktestPageResponse(BaseModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


class BacktestBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    execution_mode: BacktestBatchExecutionMode = BacktestBatchExecutionMode.INDEPENDENT
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    watchlist_id: UUID | None = None
    start_at: datetime
    end_at: datetime
    initial_cash: str = "100000"
    spec: dict[str, Any] | None = None
    user_strategy_id: UUID | None = None
    exclude_st: bool = True
    exclude_bse: bool = False
    exclude_star_market: bool = False
    exclude_chinext: bool = False
    minimum_listing_trading_days: int | None = Field(default=None, ge=1, le=5000)
    commission_rate: str = "0.0003"
    minimum_commission: str | None = "5"
    stamp_duty_rate: str = "0.0005"
    transfer_fee_rate: str = "0.00001"
    slippage_basis_points: str = "2"
    maximum_volume_participation: str | None = "0.1"
    execution_price_mode: BacktestExecutionPriceMode = BacktestExecutionPriceMode.NEXT_OPEN
    signal_timeframe: MarketTimeframe = MarketTimeframe.MINUTE_1
    auto_prepare_minute_data: bool = True
    optimistic_fill_assumption: bool = False
    position_size_ratio: str | None = "1"
    maximum_holdings: int = Field(default=5, ge=1, le=5000)
    maximum_total_exposure: str = "1"
    maximum_instrument_weight: str = "0.2"
    allow_position_addition: bool = False
    entry_ranking: str = Field(
        default="SIGNAL_STRENGTH_VOLUME_SYMBOL", min_length=1, max_length=64
    )
    benchmark_symbol: str | None = Field(default="000300.SH", max_length=32)
    maximum_entry_gap_ratio: str | None = "0.05"
    time_in_force: TimeInForce = TimeInForce.DAY
    idempotency_key: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if self.scope not in {"MANUAL", "WATCHLIST", "ALL_A_SHARES"}:
            raise ValueError("批量回测范围必须是手选股票、自选组合或全部A股")
        if self.scope == "MANUAL" and not self.instrument_ids:
            raise ValueError("手选股票回测必须至少选择一只股票")
        if self.scope == "WATCHLIST" and self.watchlist_id is None:
            raise ValueError("自选组合回测必须选择一个自选列表")
        if (self.spec is None) == (self.user_strategy_id is None):
            raise ValueError("必须且只能提供策略规则或我的策略编号之一")
        if self.start_at >= self.end_at:
            raise ValueError("回测开始时间必须早于结束时间")
        if self.execution_price_mode is BacktestExecutionPriceMode.SIGNAL_CLOSE_LIMIT:
            self.position_size_ratio = None
        if (
            self.execution_mode is BacktestBatchExecutionMode.SHARED_PORTFOLIO
            and self.position_size_ratio is None
        ):
            raise ValueError("共享资金组合必须设置单次目标仓位")
        return self
