"""UX02 quick-backtest HTTP contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphadesk_domain.market_reference import PriceAdjustmentMode


class QuickBacktestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: UUID
    start_at: datetime
    end_at: datetime
    initial_cash: str = "100000"
    spec: dict[str, Any] | None = None
    user_strategy_id: UUID | None = None
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.QFQ
    commission_rate: str = "0.0003"
    minimum_commission: str = "5"
    stamp_duty_rate: str = "0.0005"
    transfer_fee_rate: str = "0.00001"
    slippage_basis_points: str = "2"
    maximum_volume_participation: str | None = "0.1"
    idempotency_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def exactly_one_strategy(self):
        if (self.spec is None) == (self.user_strategy_id is None):
            raise ValueError("必须且只能提供策略规则或我的策略编号之一")
        if self.start_at >= self.end_at:
            raise ValueError("回测开始时间必须早于结束时间")
        return self


class ResearchBacktestPageResponse(BaseModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
