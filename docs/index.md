# AlphaDesk 文档索引

> 当前封板里程碑：**M03**。权威增量文档为 [行情基础数据与适配器](market_data.md)、[自选股业务规则](watchlists.md) 和 [ADR 0008](adr/0008-market-data-source-and-idempotency.md)。系统仍无策略、Signal、订单、风控、Broker 或实盘能力。

M03 实现入口：Migration `0003_m03_market_data_watchlists.py`；后端 `alphadesk_domain.market`、`alphadesk_api.application`；网页 `/market`；本地验收 `scripts/check_m03.ps1` 或 `scripts/check_m03.sh`。

当前里程碑：**M02 已完成**。系统具备纯领域模型、PostgreSQL 持久化模型、仓储与事务边界；尚不具备业务 API、消息发布、交易执行、认证或实盘能力。

## 阅读顺序

1. [架构总览](architecture.md)：系统边界、依赖方向与两条交易链路。
2. [开发路线图](development_roadmap.md)：M00–M14 的交付顺序和验收门槛。
3. [领域模型](domain_model.md) 与 [事件模型](event_model.md)：统一语言、事实与审计基础。
4. [数据库模型](database_schema.md)：M02 表、约束、索引、追加事实和事务边界。
5. [订单状态机](order_state_machine.md)、[可靠消息](reliable_messaging.md) 与 [风险模型](risk_model.md)：下单安全闭环。
6. [回测规则](backtest_rules.md)、[安全规范](security.md)、[测试策略](testing_strategy.md) 与 [编码标准](coding_standards.md)。
7. [架构决策记录](adr/index.md)：了解不可随意改变的架构选择。

## 按任务定位

| 变更内容 | 必读文档 |
| --- | --- |
| 策略、信号、回测 | `domain_model.md`、`backtest_rules.md`、`risk_model.md` |
| 订单、成交、执行器 | `order_state_machine.md`、`reliable_messaging.md`、`risk_model.md`、`security.md` |
| 数据库、事件、审计 | `database_schema.md`、`event_model.md`、`reliable_messaging.md`、ADR 0002、0004、0007 |
| Redis、队列、推送 | `reliable_messaging.md`、ADR 0003、0004 |
| Web 或 API | `architecture.md`、`security.md`、`coding_standards.md` |
| Broker 或行情适配器 | `architecture.md`、`risk_model.md`、ADR 0005 |

若文档与实现发生冲突，先暂停变更并更新经评审的文档或 ADR；不得以临时实现绕过既定约束。

## M02 实现入口

- 本地启动和验收：根目录 `README.md`、`compose.yaml` 与 `scripts/`。
- FastAPI：`apps/api/src/alphadesk_api/`，依赖锁在 `apps/api/requirements.lock`。
- 纯领域模型：`apps/api/src/alphadesk_domain/`；SQLAlchemy 模型、仓储和 UoW：`apps/api/src/alphadesk_api/infrastructure/`。
- Migration：`apps/api/alembic/versions/0002_m02_domain_persistence.py`；完整表设计见 `database_schema.md`。
- React：`apps/web/src/`，依赖锁在 `apps/web/package-lock.json`。
- CI：`.github/workflows/ci.yml`。

M02 已建立 18 张核心领域/审计/Outbox 表。Redis 仍仅做连接检查，未建立 Streams、业务缓存、发布器或消费者。
