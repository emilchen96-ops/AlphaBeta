# B01-B 模拟订单执行事实管道

> B01-C 已在不复制本服务事务逻辑的前提下增加 API、CLI、Demo 和页面，见
> [模拟执行 API、CLI 与网页](simulated_broker_ui.md)。

> B01-B 本身实现本地模拟订单的后端执行闭环；B01-C 仅在其上增加受控传输和展示层。执行仍不调用
> Redis、MiniQMT、Windows Agent、真实行情网络或真实 Broker。B01-C 尚未开始，B01 整体尚未完成。

## 服务与输入

`SimulatedBrokerExecutionService` 接受 `order_id`、调用方显式提供的
`ExecutionMarketSnapshot`、幂等键、`correlation_id` 和请求时间。服务不自行查询行情；历史收盘价
也不能被服务包装成实时快照。它只执行 `QUEUED`、`BROKER_ACCEPTED` 或
`PARTIALLY_FILLED` 订单，并复用 B01-A `SimulatedBrokerAdapter`。

执行前在同一 PostgreSQL 事务中使用 advisory transaction lock 收敛幂等键，再依次锁定 Order、
`SUBMIT_ORDER` Command、对应 Outbox、模拟账户、现金和相关持仓。剩余数量始终从已持久化 Fill
求和计算，不信任调用方或 Order 的缓存成交量。

## BrokerExecutionAttempt

每次实际调用模拟 Broker 都追加一个 `broker_execution_attempts` 事实，记录：

- Broker/费用/滑点版本、请求指纹和执行模式；
- Order、Command、账户和标的身份；
- 连续的 `attempt_number`、输入订单状态及结果状态；
- 原始订单量、先前累计成交量、本次尝试量、本次成交量和剩余量；
- 白名单市场/账户快照、拒绝代码、消息和 UTC 时间。

`idempotency_key`、`(order_id, attempt_number)` 和 `(command_id, attempt_number)` 均唯一。Attempt
只追加，不提供通用更新或删除。快照不保存凭据、数据库 URL 或本地路径。

## 状态推进

首次正常执行按既有 M05 状态机推进：

```text
QUEUED -> DISPATCHED -> EXECUTOR_ACCEPTED -> BROKER_SUBMITTED -> BROKER_ACCEPTED
```

随后全部成交进入 `FILLED`，首次部分成交进入 `PARTIALLY_FILLED`。后续部分成交若仍未完成，只追加
Attempt、Fill 和事件，不伪造 `PARTIALLY_FILLED -> PARTIALLY_FILLED` 迁移；累计成交达到订单量时才
合法迁移到 `FILLED`。`NO_FILL` 保存 Attempt、保持 `BROKER_ACCEPTED` 或原部分成交状态，不创建 Fill。

执行接受前发现过期时由合法路径进入 `EXPIRED`。市场/快照级拒绝使用
`DISPATCHED -> EXECUTOR_REJECTED`；Broker 级拒绝使用 `BROKER_SUBMITTED -> FAILED`。任何终态均不能
再次生成 Fill。

## Fill 与 M04 原子记账

B01-A `FillDraft` 被映射到既有 `fills` 表，不创建第二套成交模型。B01-B Fill 额外关联 Attempt、
Command、连续 `sequence_number` 和稳定 `SIMULATED:{attempt_id}:{sequence}` 引用。数据库以
`(execution_attempt_id, sequence_number)` 和执行引用双重唯一约束防止重复成交。

每个新 Fill 必须调用既有 `FillAccountingService.apply_in_uow`。该入口复用 M04 的现金、移动加权
成本、已实现盈亏和账本公式，但不自行提交；外层 B01-B 服务统一提交 Attempt、Order/Transition、
Fill、CashBalance、Position、两类账本、AccountSnapshot、Reconciliation、事件和审计。BUY 费用计入
持仓成本，SELL 费用从收入扣除，印花税仅由 B01-A 费用模型对 SELL 计算。成交后的核对必须为
`MATCHED`，否则整个执行事务回滚。

## Command 本地消费与 Outbox 抑制

首次本地模拟执行把 Command 置为 `CONSUMED`，同时记录
`consumed_by=LOCAL_SIMULATED_BROKER`。对应 Outbox 置为 `SUPPRESSED`，原因固定为
`LOCAL_SIMULATED_EXECUTION`。`SUPPRESSED` 与 `PUBLISHED` 语义不同；消息仍保留审计，但未来 Publisher
只查询 `PENDING`，因此不能把已在本地成交的命令再次外发。

Command 消费和 Outbox 抑制与执行事务一起提交。任一步失败时，Command 恢复 `PENDING`，Outbox
恢复 `PENDING`，且不残留 Attempt、Fill、账本、投影、事件或审计的半套事实。

## 幂等、并发与完整性

相同幂等键与相同执行指纹返回原 Attempt、Fill 和既有记账结果，不重复修改现金或持仓。相同键但
市场快照、剩余数量或费用/滑点配置摘要不同，返回
`BROKER_EXECUTION_IDEMPOTENCY_CONFLICT`。同一 Order 的不同幂等键最终仍由 Order 行锁和数据库唯一
约束收敛；终态返回 `BROKER_ORDER_NOT_EXECUTABLE`。

`SimulatedExecutionIntegrityService` 只读检查 Attempt/Fill 序号、关联、累计成交量、状态、金额费用、
Fill 与账本的一次性关系，以及已消费 Command 的 Outbox 是否不可发布。它只报告差异，不自动修复。
`SimulatedExecutionQueryService` 提供内部按 Order/Attempt 查询；B01-B 不暴露 API。

## 安全边界

R01 PASS 只允许创建 Order，不保证成交。B01-B 仍无身份认证、交易级行情、Redis 消息发布、外部
Broker、MiniQMT、实盘、自动策略下单、API、CLI、前端或回测执行能力。
