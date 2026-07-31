# 停复牌与 Instrument 生命周期

## 交易状态

`InstrumentTradingStatus` 按 Instrument、Session 日期与来源保存 `TRADING`、`SUSPENDED`、`RESUMED` 或 `UNKNOWN`。`UNKNOWN` 不等于停牌；数据缺失时系统沿用兼容执行语义并附 WARNING。

- 已知 `SUSPENDED` 的日期不模拟成交。
- 停牌日缺少 RAW 日线不计为数据缺口。
- 逐股技术指标窗口会跳过已知停牌日，并在统一市场窗口之前继续向前取该股票的真实
  有效 K 线；不会伪造价格、成交量或“补一根停牌 K 线”。
- 全市场事件条件仍使用统一市场交易日窗口。逐股向前取数只补足指标所需样本，
  不会把某只停牌股票的事件观察期延长到更早日期。
- `RESUMED` 的第一根日线正常参与策略、成交和估值。
- BT01/RT01 的待处理订单在停牌 Session 保留，下一可交易 Session 再尝试；DAY 订单仍遵守引擎既有 Session 结束语义。

## 生命周期

`InstrumentLifecycleEvent` 支持 `LISTED`、`DELISTED`、`SUSPENDED_LONG_TERM`、`RESUMED` 与 `STATUS_CHANGED`。Instrument 同步维护 `listed_at`、`delisted_at` 和 active：

- 上市前与退市后不期待 K 线；
- inactive 不进入默认当前活跃股票池；
- inactive 仍可查询历史数据和运行显式历史研究；
- 状态变化不会删除历史事实。
- 新股在筛选日期尚未积累足够真实交易历史时标记为
  `LISTING_HISTORY_TOO_SHORT`，不阻塞其他股票；达到规则最低样本数后自动恢复正常计算。
- 筛选日期已经退市的股票标记为 `DELISTED`，不误报为行情下载失败。
- 当前停牌且已有足够历史数据的股票可计算历史条件，但不会作为当日可交易候选输出；
  长期没有新 K 线且超出配置阈值时单独标记为 `STALE_DATA`。

同步与查询通过 `/api/v1/market-reference/suspensions*`、`/instrument-lifecycle*` 或
`alphadesk_api.cli.market_reference`。当前数据质量取决于已同步的停牌和生命周期事实；
未知状态不会被武断当成停牌。Fixture 仅用于离线验收。
