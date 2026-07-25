# RT01 日线历史行情回放

## UX02-B 页面名称

研究模式中“历史回放”显示为“逐日查看”，入口只出现在已完成的回测详情中。它复用 RT01
解释策略在每个历史交易日的条件、信号、模拟持仓和权益变化，不是另一套回测。

D02 的回放价格边界与 BT01 相同：策略输入可选 RAW/QFQ，成交与账本固定 RAW；Session 来自交易日历，暂停/恢复/播放速度不会改变停牌与成交结果。当前仍仅支持日线回放。

RT01 把 D01 PostgreSQL 日线按交易 Session 逐日推进，并复用 BT01 的
`HistoricalSessionProcessor`、时间模型和指标口径。业务链路为：

`ReplayClock → Strategy → Signal → R01 → M05 → B01 → Fill → M04`。

每个回放创建独立 `RT01-*` 模拟账户和 `StrategyRun(environment=REPLAY)`。T 日收盘
Signal 最早在下一根有效日线的开盘撮合；费用、滑点、成交量限制、T+1、平均成本账本与
BT01 一致。回放只读历史行情，不访问外部网络，不连接 Windows Agent、MiniQMT 或券商；
订单 Outbox 固定为 `SUPPRESSED/REPLAY_ENGINE`。

## 创建与使用

网页入口为 `/replays`，详情为 `/replays/:replayId`。创建时选择策略、参数、Instrument、
日期、初始资金、订单/费用/滑点/成交量上限和初始速度。MANUAL 模式用“单步”推进，自动
速度支持 X1、X10、X100；速度只改变 Session 之间的等待时间，不改变业务时间或结果。

CLI：

```text
python -m alphadesk_api.cli.replays create --help
python -m alphadesk_api.cli.replays list
python -m alphadesk_api.cli.replays show --replay-id <UUID>
python -m alphadesk_api.cli.replays start --replay-id <UUID> --idempotency-key <KEY>
python -m alphadesk_api.cli.replays pause --replay-id <UUID> --idempotency-key <KEY>
python -m alphadesk_api.cli.replays resume --replay-id <UUID> --idempotency-key <KEY>
python -m alphadesk_api.cli.replays step --replay-id <UUID> --idempotency-key <KEY>
python -m alphadesk_api.cli.replays set-speed --replay-id <UUID> --speed X10 --idempotency-key <KEY>
python -m alphadesk_api.cli.replays stop --replay-id <UUID> --idempotency-key <KEY>
python -m alphadesk_api.cli.replays verify-integrity --replay-id <UUID>
python -m alphadesk_api.cli.replays run-demo
```

## 事实与一致性

`replay_runs` 保存控制状态、游标、计数、lease、终态摘要和配置快照；控制动作、Timeline、
权益点均是 PostgreSQL 权威事实。Signal、RiskDecision、Order、Fill 和 M04 账本继续写入
既有表，以独立账户、StrategyRun 与 correlation ID 关联，不复制交易事实表。

Integrity 检查事件序号连续性、计数、账户归属及账本隔离。相同数据与配置下，完成的 RT01
运行必须与 BT01 的 Signal 语义、订单方向和数量、成交价格和数量、最终权益、费用、收益率、
最大回撤和已实现盈亏一致。

边界：当前只有 DAY_1，不含分钟、Tick、撮合队列、真实延迟、停复牌日历增强或复权因子增强；
历史回放结果仅供研究，不代表未来收益。
