# ADR 0013：免费行情抓取使用独立单 Leader Worker

- 状态：Accepted
- 日期：2026-07-15

## 背景

在 FastAPI lifespan 中轮询会随 API worker 数量重复抓取，放大免费源压力，并把 HTTP 可用性与外部数据故障绑定。

## 决策

行情轮询仅运行在独立 `market_worker` 进程。多实例通过带 owner 校验的 Redis 租约选主；provider guard 固定单并发、5 秒最短间隔、两次有 jitter 重试，以及 5 次失败/600 秒开放的熔断状态机。每轮运行审计写 PostgreSQL。

## 后果

API 可独立扩缩容，免费源不会因 API 进程数重复调用。Redis 故障会暂停抓取和临时推送，但不会破坏 PostgreSQL 审计事实。Worker 不具备任何交易权限。
