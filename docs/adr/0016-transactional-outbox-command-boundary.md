# ADR 0016：Transactional Outbox 命令边界

- 状态：Accepted
- 日期：2026-07-16

## 决策

人工确认、OrderAction、QUEUED Transition、SUBMIT_ORDER Command、DomainEvent、AuditLog 和 PENDING Outbox 必须在同一 PostgreSQL 事务提交。Command 与 Outbox 使用同一版本化白名单 payload 和 canonical SHA-256 hash。

M05 不发布 Outbox，不写 Redis 订单消息，也不调用 Executor/Broker。`QUEUED` 和 `PENDING` 均不得被解释为外部发送成功。

## 后果

本地事实不会出现“状态已变但命令丢失”的双写窗口；发布与重试可以在未来阶段独立实现。当前系统不会执行交易，也不会创建 Fill 或账本变化。
