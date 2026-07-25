# BT01 A股日线回测

D02 增加 `strategy_price_adjustment_mode=RAW|QFQ`。策略可读 QFQ，但 Session Open 成交、Session End 估值、Order、Fill、费用和账本始终使用 RAW；开放日来自交易日历，已知停牌日不会成交。分钟回测仍未实现。

BT01 提供同步、确定性、可审计的本地日线回测。链路复用现有事实管道：

`MarketBar -> BacktestClock -> Strategy -> Signal -> R01 -> M05 -> B01 -> Fill -> M04`

每次运行创建独立的 `SIMULATED` 账户，并通过 M04 入金和账本服务初始化资金。运行之间以及与普通模拟账户之间不共享现金、持仓、订单或成交。

## 支持范围

- A 股 `DAY` K 线、单策略、一个或多个标的。
- quantity 型 BUY/SELL 信号，MARKET/LIMIT 订单，DAY/GTC 有效期。
- 固定费用、滑点和最大成交量参与率。
- 全部成交、部分成交、NO_FILL、现金或可卖持仓不足。
- 权益曲线、回撤、费用、成交和闭合交易绩效。
- 同步 API、CLI 和只读结果页面。

不支持分钟线、Tick、实时成交驱动、外部网络补数、Redis 任务队列或真实券商账户。
浏览器正式回测固定使用已由 MiniQMT 同步到 PostgreSQL 的历史日线；回测过程本身不会连接
MiniQMT 实时接口，也不会读取或写入券商账户。target_weight 信号不会被猜测换算为数量。

## 运行与幂等

`POST /api/v1/backtests` 同步执行。服务端在开始前校验标的、K 线和交易日数量限制。规范化配置经 canonical JSON 和 SHA-256 生成 fingerprint；相同 idempotency key 与 fingerprint 返回原运行，不会重复开户、入金或执行；相同 key 配置不同时返回 `BACKTEST_IDEMPOTENCY_CONFLICT`。

失败会保留已经提交的事实用于审计，并把 BacktestRun 标为 `FAILED`；第一版不支持暂停、恢复或断点续跑。

## API 与 CLI

API 提供运行列表、详情、指标、权益、交易、Signal、RiskDecision、Order、Fill、Timeline 和 Integrity 查询。

```text
python -m alphadesk_api.cli.backtests run --strategy-key sma_crossover --instrument <UUID> --start 2024-01-01 --end 2024-06-01 --initial-cash 1000000 --idempotency-key bt-demo-1
python -m alphadesk_api.cli.backtests list
python -m alphadesk_api.cli.backtests show --backtest-id <UUID>
python -m alphadesk_api.cli.backtests metrics --backtest-id <UUID>
python -m alphadesk_api.cli.backtests verify-integrity --backtest-id <UUID>
python -m alphadesk_api.cli.backtests run-demo
```

`run-demo` 仅可在 development/test 环境使用；它会幂等建立带 `BT01_DEMO` 来源标识的确定性本地 Fixture，再从 PostgreSQL 读取运行，不联网。

浏览器页面不提供测试数据源开关，统一提交 `data_source_code=MINIQMT`。`BT01_DEMO` 仅用于
CLI、自动化测试和确定性开发验收。

## 风险提示

回测结果不代表未来收益。T 日收盘后形成的 Signal 最早在下一根可用日线的开盘执行；费用和滑点均为模拟配置，部分公司行为可能尚未完整还原。本功能不会连接券商，也不会产生真实交易。
