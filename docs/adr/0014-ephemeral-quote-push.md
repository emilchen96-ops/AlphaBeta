# ADR 0014：最新报价和网页推送使用可重建 Redis 临时链路

- 状态：Accepted
- 日期：2026-07-15

## 背景

高频覆盖式报价不适合逐条写入业务事实表，但网页需要低延迟更新和断线恢复。可靠交易消息的 Redis Streams/Outbox 语义不应被行情噪声复用。

## 决策

最新报价以 instrument ID 为键写 Redis，原子维护内容 hash、单调 revision、时间乱序保护和 TTL；只在内容变化时发布普通 Pub/Sub。API 每进程只有一个 Redis listener，向有界客户端队列分发。断线恢复从 quote cache 发 snapshot。PostgreSQL 只保存来源能力、K 线和 `market_realtime_runs` 审计。

## 后果

Redis 数据可丢失且可重建，网页慢消费者不会造成无限内存增长。Pub/Sub 消息不保证送达，因此绝不能承载订单、成交、风控、资金或 Broker 指令。
