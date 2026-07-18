# ADR 0017：确定性日线回测复用事实管道

- 状态：Accepted
- 日期：2026-07-18

## 决策

BT01 使用同步的 PostgreSQL 本地事件循环。策略只生成 Signal；回测订单必须继续通过 R01、M05、B01 和 M04。每次 BacktestRun 创建独立模拟账户。T 日 close 信号只能在下一根可用日线 open 执行，所有业务时间来自 BacktestClock。

回测内部确认只接受 `environment=BACKTEST`、当前运行账户、STRATEGY 来源、BACKTEST_ENGINE actor 和 PASS 风控决定。对应 Outbox 明确写为 `SUPPRESSED`，原因是 `BACKTEST_ENGINE`，不伪装成已发布，也不写 Redis。

## 原因

复用已封板事实管道避免第二套 Order、Fill、费用和账本规则；独立账户与被抑制的本地 Outbox 同时提供隔离、可审计性和未来数据边界。

## 后果

第一版 POST 是耗时的同步请求，受 bars/instruments/sessions 上限保护；不支持暂停恢复、分钟/Tick、多策略、外部行情补数或真实 Broker。RT01 可在此事实模型上增加历史回放，但不得改变 BT01 的确定性时间语义。
