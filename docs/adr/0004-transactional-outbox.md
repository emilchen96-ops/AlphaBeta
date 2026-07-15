# ADR 0004：使用 Transactional Outbox

- 状态：Accepted

## 背景

订单状态写入和消息发布跨越 PostgreSQL 与 Redis，单纯双写会在故障时产生不一致。

## 决策

订单/事件状态与 OutboxMessage 在同一 PostgreSQL 事务中写入；独立发布器异步、可重试地投递至 Redis Streams。

## 原因

保证已确认的业务事实始终拥有可恢复的待发布记录，避免“订单存在但命令丢失”或“命令已发但订单未提交”。

## 后果

需要 Outbox 清理、监控、去重和延迟处理机制；发布可能是最终一致的。

## 被否决方案

应用代码中直接先后写数据库与 Redis；分布式两阶段提交。
