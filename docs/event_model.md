# 事件模型

> M04.1A 不为每条 Quote 创建 `DomainEvent` 或 Outbox。临时行情通过 Redis Pub/Sub 传送；只有运行摘要、历史 K 线同步以及必要审计进入 PostgreSQL，Pub/Sub 绝不能复用于订单可靠投递。

> M04 在业务事务内记录账户创建/更新、资金入出、成交记账、估值和核对领域事件及审计日志；尚不发布 Outbox，也不创建 Redis 消费者。

## M04.1A 行情更新语义

实时更新以 `instrument_id`、`source_code`、`quote_time`、`received_at`、payload hash 和单调 `revision` 标识。相同 payload 只刷新 TTL，不发布重复增量；更旧的 `quote_time` 被拒绝。WebSocket 的 snapshot/update/heartbeat 是可丢弃的展示消息，不是领域事实，也不提供重放或至少一次交付保证。`market_realtime_runs` 保存可审计运行结果，但不把完整上游响应或全部订阅集合写入事件日志。

## M03 行情与自选股事件

M03 写入 `INSTRUMENT_IMPORTED`、`INSTRUMENT_MAPPING_CREATED`、`MARKET_SYNC_STARTED`、`MARKET_BARS_INGESTED`、`MARKET_SYNC_SUCCEEDED`、`MARKET_SYNC_PARTIALLY_SUCCEEDED`、`MARKET_SYNC_FAILED`，以及自选列表创建/修改/删除、条目添加/修改/移除/重排事件。每个写操作同步追加审计日志并共享 Correlation ID。为避免越界，M03 只落 `domain_events` 与 `audit_logs`，不创建 Outbox 消息、不发布 Redis Streams。

所有领域事件使用统一事件信封，作为审计、内部发布和可靠消息的共同语义。事件本身不可原地修改；需要更正时，发布新的更正或补偿事件，并保留原始事件。

## 事件信封

| 字段 | 含义 |
| --- | --- |
| `event_id` | 全局唯一且不可变的事件标识 |
| `event_type` | 稳定、可版本演进的事件类型 |
| `event_time` | 业务事实发生的时间 |
| `received_time` | AlphaDesk 首次接收该事实的时间 |
| `processed_time` | 当前处理步骤完成的时间 |
| `source` | 产生者，如策略、API、执行器、Broker 或对账器 |
| `correlation_id` | 串联同一业务流程的标识 |
| `causation_id` | 直接导致本事件的前序事件或命令标识 |
| `sequence` | 同一实体或流内的有序序号 |
| `schema_version` | Payload 的显式版本 |
| `payload` | 经验证的业务数据，最小化且可序列化 |
| `metadata` | 非业务处理元数据，如追踪、来源版本或重试信息 |

## 时间与数据规则

1. 数据库存储统一使用 UTC，并在边界处明确转换和展示时区。
2. `event_time` 与 `received_time` 必须分开：外部数据迟到、回放和对账时不能以接收时间伪造业务时间。
3. `processed_time` 记录每个处理阶段，不代替前两个时间。
4. 事件按其 `schema_version` 解释；破坏性字段变更必须发布新版本并保留兼容策略。
5. Payload 与 metadata 不能包含密码、密钥、Token、完整账户凭证或其他敏感机密；引用安全存储中的标识即可。
6. 事件落库、发布、消费及失败处理均应可由 `event_id`、`correlation_id` 和 `causation_id` 追溯。

事件日志是事实记录而非可变状态缓存。最新状态应由受控投影或领域聚合得出，但历史事件必须保留以支持审计与重放。

## M02 持久化状态

M02 已实现 `domain_events`、`audit_logs` 和 `outbox_messages` 表及追加型仓储接口。`event_id`、实体序列、correlation/causation、schema 版本、UTC 时间和 JSONB 载荷均可持久化；事件与 Outbox 的唯一键由数据库强制执行。M02 未实现事件发布、重放、消费、投影更新或 Redis Streams，这些能力从 M03 开始建设。
