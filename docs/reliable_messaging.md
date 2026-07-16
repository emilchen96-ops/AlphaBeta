# 可靠消息与命令

> M05 只完成 Transactional Outbox 的原子写入边界：`order.commands.submit.v1` 保持 PENDING，未发布 Redis Streams。Command/Outbox 共享版本化白名单 payload 与 canonical SHA-256；后续 Publisher 不在本阶段。详见 ADR 0016。

> M03 边界说明：行情摄取和自选股写入领域事件与审计，但不创建 Outbox 消息、不启动发布器或 Redis Streams。现有 Outbox 仅保留 M02 数据模型能力；可靠消息的发布/消费仍未启用。

## 基本模型

`Transactional Outbox` 指在与订单、事件或状态迁移相同的 PostgreSQL 事务内写入待发布消息。事务提交后，发布器负责将未发布的 OutboxMessage 投递到 Redis Streams；投递失败不会使已提交业务事实消失。

Redis Streams 用于后端和执行器之间的可靠命令、回执和恢复协作。Consumer Group 使多个消费者可协调读取；消费者必须在成功完成持久化处理后 ACK。未 ACK 的 Pending 消息必须可被检查、认领和恢复。

## 投递与幂等

系统按“至少一次投递”设计，绝不把“恰好一次”作为 Redis 的假设。每个命令有全局唯一的 `command_id` 并指向 `order_id`；执行器和后端均必须在持久化去重记录后幂等处理重复命令、重复回执和重复 Broker 回报。

1. 写入订单状态和 OutboxMessage 必须在同一个 PostgreSQL 事务完成。
2. 发布器可重试投递；重复投递由 `command_id` 去重。
3. 消费者先执行可恢复的持久化状态变更，再 ACK；不得在业务事实尚未记录时 ACK。
4. 命令包含签发时间和有效期。过期命令由执行器拒绝，并写入明确回执和审计，而非静默丢弃。
5. 回执也带唯一标识、`command_id`、`order_id`、相关状态及 `correlation_id`；重复回执必须安全地合并或忽略。

## 故障恢复

- 断网期间，后端保留 Outbox；执行器保留已见命令和已发/待发回执的恢复状态。
- 恢复连接后，发布器重试未发布消息，消费者从 Pending 列表认领超时消息，并以幂等键恢复。
- 执行器重启时必须先加载其设备身份、最近处理命令和订单对账状态，再开始消费新命令。
- 对命令是否已送达、Broker 是否已受理存在不确定性时，订单转为 `RECONCILIATION_REQUIRED`，不得盲目重发下单。

WebSocket 只用于网页的实时展示与状态订阅，不能承担可靠交易指令投递、命令确认或故障恢复职责。

## M02 已实现与未实现

M02 已实现 `order_commands` 和 `outbox_messages` 的持久化结构、幂等唯一键、待处理索引，以及同一 Unit of Work 内与订单/事件事实原子写入的能力。Redis Streams、Outbox 轮询/发布、ACK、Pending 认领、消费者去重和执行器回执均未实现，属于 M03 及后续里程碑。任何代码不得因为表已经存在就声称可靠消息链路已经可用。
