# 领域模型

本文件定义业务概念与关系，不规定 ORM、表结构或 API 实现。所有实体的持久化事实、历史状态和审计记录以 PostgreSQL 为准。

| 对象 | 职责 | 主要关系 |
| --- | --- | --- |
| `TradingAccount` | 表示一个受管理的交易账户及其市场、权限、运行模式和风险边界 | 拥有 Position、Order；关联 ExecutorDevice |
| `Position` | 表示账户在某 Instrument 上的已确认仓位与成本基础 | 从 Fill 与对账结果投影；属于 TradingAccount |
| `Instrument` | 表示可交易标的及代码、市场、货币、交易规则和状态 | 被 Signal、Order、Fill、Position 引用 |
| `Strategy` | 表示策略的稳定身份、归属和启停状态 | 包含多个 StrategyVersion，只产生 Signal |
| `StrategyVersion` | 表示不可变的策略版本、参数、数据契约和发布信息 | 属于 Strategy；生成 Signal；被回测记录引用 |
| `Signal` | 策略或受控 AI 产生的交易意图，不是订单 | 指向 Instrument、StrategyVersion；送入风险决策 |
| `RiskDecision` | 对 Signal 或 OrderCommand 的可解释准入结果 | 关联输入、规则版本、理由及允许条件 |
| `Order` | 代表贯穿生命周期的可审计交易订单聚合 | 由获准命令创建；遵守状态机；关联 Fill |
| `OrderCommand` | 代表向执行器发出的、具有效期和幂等键的命令 | 指向一个 Order 与 `command_id`；由 Outbox 可靠投递 |
| `Fill` | 代表 Broker 报告的已成交事实 | 属于 Order；驱动 Position 投影与审计 |
| `DomainEvent` | 代表已发生且不可变的领域事实 | 关联实体、相关 ID、时间与 schema 版本 |
| `AuditLog` | 记录关键操作的谁、何时、为何、前后状态和结果 | 可关联任一领域对象和 DomainEvent |
| `OutboxMessage` | 与业务事实同事务落库、等待可靠发布的消息 | 通常承载 DomainEvent 或 OrderCommand |
| `ExecutorDevice` | 表示已登记的 Windows 执行器设备及其身份、状态和权限 | 接收 OrderCommand；可被吊销或限制 |

## 关键关系与边界

```mermaid
erDiagram
  TradingAccount ||--o{ Position : holds
  TradingAccount ||--o{ Order : owns
  TradingAccount }o--|| ExecutorDevice : assigned_to
  Strategy ||--o{ StrategyVersion : versions
  StrategyVersion ||--o{ Signal : emits
  Signal ||--o| RiskDecision : evaluated_by
  Instrument ||--o{ Signal : targets
  Instrument ||--o{ Order : trades
  Order ||--o{ OrderCommand : dispatched_as
  Order ||--o{ Fill : receives
  Order ||--o{ DomainEvent : records
  DomainEvent ||--o{ AuditLog : auditable_by
  DomainEvent ||--o| OutboxMessage : published_as
```

策略和 AI 均不得直接创建 Broker 请求。只有经过 RiskDecision、订单状态机与审计后的 OrderCommand 才可进入执行器命令链路。Position 是成交和对账事实的投影，不能以手工修改替代对账。
