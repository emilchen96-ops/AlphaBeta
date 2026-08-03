# 架构决策记录（ADR）索引

> M05 新增：[ADR 0015](0015-order-state-machine-and-manual-confirmation.md) 与 [ADR 0016](0016-transactional-outbox-command-boundary.md)。

> M04.1A 新增：[ADR 0012](0012-free-provider-boundary.md)、[ADR 0013](0013-independent-market-worker.md)、[ADR 0014](0014-ephemeral-quote-push.md)。

- [0008：行情来源边界、优先级与幂等键](0008-market-data-source-and-idempotency.md)

| ADR | 决策 |
| --- | --- |
| [0001](0001-modular-monolith.md) | MVP 采用模块化单体 |
| [0002](0002-postgresql-source-of-truth.md) | PostgreSQL 是业务事实唯一来源 |
| [0003](0003-redis-streams-messaging.md) | Redis Streams 用于可靠命令与回执流 |
| [0004](0004-transactional-outbox.md) | 使用 Transactional Outbox 保证事实与发布一致性 |
| [0005](0005-windows-execution-agent.md) | Windows 本地执行器作为交易安全边界 |
| [0006](0006-two-layer-risk-control.md) | 后端与执行器实施双层风控 |
| [0007](0007-domain-persistence-separation.md) | 分离纯领域模型与 SQLAlchemy 持久化实现 |
| [0008](0008-market-data-source-and-idempotency.md) | 行情来源边界、优先级与幂等键 |
| [0011](0011-account-ledger-and-projections.md) | 模拟账户采用只追加账本与可重建投影 |
| [0012](0012-free-provider-boundary.md) | 免费行情采用显式能力与用途边界 |
| [0013](0013-independent-market-worker.md) | 免费行情抓取使用独立单 Leader Worker |
| [0014](0014-ephemeral-quote-push.md) | 最新报价和网页推送使用可重建 Redis 临时链路 |
| [0017](0017-deterministic-daily-backtest-pipeline.md) | 日线回测复用事实管道并采用确定性 T+1 时间模型 |
| [0018](0018-tradingagents-worker-adapter.md) | 固定上游 TradingAgents Graph 并由独立 Worker 适配运行 |

除非有新的 ADR 替代，以下决策均为 `Accepted` 并对后续实现有效。
