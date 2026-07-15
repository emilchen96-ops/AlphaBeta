# 架构决策记录（ADR）索引

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

除非有新的 ADR 替代，以下决策均为 `Accepted` 并对后续实现有效。
