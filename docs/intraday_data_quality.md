# D03 分钟数据质量与Readiness

分钟质量运行复用追加式 `market_data_quality_runs/issues`。检查 Session 对齐、午休/盘外时间、缺失 Bar、每日数量、OHLCVA、来源冲突、聚合一致性和 QFQ 因子可用性。问题命名空间使用 `INTRADAY_*`，包括 `INTRADAY_MISSING_BAR`、`INTRADAY_TIMESTAMP_MISALIGNED`、`INTRADAY_UNEXPECTED_BAR_COUNT` 和 `INTRADAY_AGGREGATION_MISMATCH`。

缺口规则：仅对 D02 日历开放、生命周期有效且状态为 TRADING/RESUMED 的日期期待 Bar；SUSPENDED 排除；UNKNOWN 作为 WARNING；不补零、不生成虚假完整窗口。

Readiness 分别报告 1/5/15/30/60 分钟数据、BT02 5m/15m 数据和分钟回放数据。数据状态与代码状态分开：即使分钟数据 READY，`minute_backtest` 与 `minute_replay` 仍是 `NOT_IMPLEMENTED`，页面显示“代码尚未开发”。READY 不代表收益、实时性或实盘授权。

RAW 是权威价格。QFQ 按 D02 同一交易日的日级因子派生，只调整 OHLC；volume/amount 保留原始语义，不覆盖 RAW。缺因子返回 `MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE` 与 Correlation ID。
