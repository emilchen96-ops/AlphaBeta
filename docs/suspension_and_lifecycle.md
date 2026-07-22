# 停复牌与 Instrument 生命周期

## 交易状态

`InstrumentTradingStatus` 按 Instrument、Session 日期与来源保存 `TRADING`、`SUSPENDED`、`RESUMED` 或 `UNKNOWN`。`UNKNOWN` 不等于停牌；数据缺失时系统沿用兼容执行语义并附 WARNING。

- 已知 `SUSPENDED` 的日期不模拟成交。
- 停牌日缺少 RAW 日线不计为数据缺口。
- `RESUMED` 的第一根日线正常参与策略、成交和估值。
- BT01/RT01 的待处理订单在停牌 Session 保留，下一可交易 Session 再尝试；DAY 订单仍遵守引擎既有 Session 结束语义。

## 生命周期

`InstrumentLifecycleEvent` 支持 `LISTED`、`DELISTED`、`SUSPENDED_LONG_TERM`、`RESUMED` 与 `STATUS_CHANGED`。Instrument 同步维护 `listed_at`、`delisted_at` 和 active：

- 上市前与退市后不期待 K 线；
- inactive 不进入默认当前活跃股票池；
- inactive 仍可查询历史数据和运行显式历史研究；
- 状态变化不会删除历史事实。

同步与查询通过 `/api/v1/market-reference/suspensions*`、`/instrument-lifecycle*` 或 `alphadesk_api.cli.market_reference`。当前数据质量取决于配置的 Provider，Fixture 仅用于离线验收。
