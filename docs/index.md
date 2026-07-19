# AlphaDesk 文档索引

> 当前研究里程碑为 **A01 完成**：版本化 Prompt、Disabled/Fake Provider、AIAnalysisRun、ResearchInsight、Evidence、API、CLI 和页面见 [ai_research_assistant.md](ai_research_assistant.md)。真实 Provider 当前不可用且默认禁用；AI 输出仅供研究，不创建 Signal 或订单。SC01 与 N01 均已完成，BT01 仍为部分完成，下一步仅为 BT01 补全与封板；RT01 尚未开始。

> 当前资讯里程碑为 **N01 完成**：手工/RSS 来源、RawDocument、规范化与去重、MarketEvent、Instrument/主题关联、API、CLI 和页面见 [information_center.md](information_center.md)。当前尚未经过 AI 分析，不构成投资建议，不创建订单。

> 当前研究工具里程碑为 **SC01 完成**：统一 Scanner、两个 A 股历史日线规则、ScanRun/ScanResult、API、CLI 和页面见 [scanners.md](scanners.md)。结果仅为历史规则筛选，不代表投资建议，不是实时扫描，不创建 Signal 或订单。

> 当前执行里程碑为 **B01 完成开发，等待最终环境验收**：B01-A Broker 契约与确定性计算见
> [simulated_broker.md](simulated_broker.md)；B01-B Attempt、Fill、M04 原子记账、Command 消费和
> Outbox 抑制见 [simulated_execution_pipeline.md](simulated_execution_pipeline.md)；B01-C API、CLI、Demo
> 与网页见 [simulated_broker_ui.md](simulated_broker_ui.md)。系统仍无 Windows 执行器、MiniQMT、外部
> Broker 或实盘能力；下一阶段仅规划 BT01 日线回测。

> 当前风险里程碑为 **R01 完成**：纯规则核心见 [risk_engine.md](risk_engine.md)，快照、持久化、幂等、查询和 M05 安全门见 [risk_decision_pipeline.md](risk_decision_pipeline.md)，只读页面和关联边界见 [risk_ui.md](risk_ui.md)。下一阶段为 B01 模拟 Broker；系统仍无执行器、MiniQMT 或实盘能力。


> 当前策略里程碑为 **S02 完成**：S02-A 指标与策略库、S02-B1 批量研究后端和 S02-B2 批量研究页面均已完成。后端契约见 [strategy_experiments.md](strategy_experiments.md)，页面与边界见 [strategy_experiments_ui.md](strategy_experiments_ui.md)。下一阶段为 R01 轻量风控，尚未开始。

> 当前策略阶段为 **S02-B1 批量研究后端**：参数网格、实验生命周期、事务、幂等和
> Signal 对比见 [strategy_experiments.md](strategy_experiments.md)。S02-B2 尚未开始。

> 当前策略阶段为 **S02-A 技术指标与基础策略库**：S01-A/B/C 已完成开发，用户决定
> 跳过 S01 最终专项审查；指标、三套内置策略和安全边界见
> [strategy_library.md](strategy_library.md)。S02-B 尚未开始。

> S01-A、S01-B、S01-C 功能开发已完成；策略目录、研究运行 API 与页面见 [strategy_api_and_ui.md](strategy_api_and_ui.md)。S01 最终短审查与封板尚未完成，下一步不是直接进入 N01。

> 当前策略里程碑为 **S01-B 历史策略运行器**：契约见 [strategy_interface.md](strategy_interface.md)，历史运行、幂等、Signal 持久化和失败事务见 [strategy_runner.md](strategy_runner.md)。本阶段没有订单、撮合、资金/持仓变化、API、CLI、页面或实盘能力。

> 当前封板里程碑：**M05 订单事实管道**。业务规则见 [orders.md](orders.md)，人工确认见 [order_confirmation.md](order_confirmation.md)，本地 Outbox 见 [transactional_outbox.md](transactional_outbox.md)，决策见 ADR 0015–0016。QUEUED/PENDING 均不表示已发送；系统无 Broker、Fill 或实盘能力。下一阶段仅规划 S01 统一策略接口，策略只能产生 Signal。

> M04.1A sealed status: BaoStock is historical-only, the real-time provider is `disabled`, and no other free real-time source is being added. The retained Redis/WebSocket/UI path awaits a later Windows Agent/MiniQMT integration; no order validation may rely on real-time market data.

> 当前开发里程碑：**M04.1A**。免费真实行情见 [free_market_data.md](free_market_data.md)，独立 Worker 见 [free_market_worker.md](free_market_worker.md)，推送协议见 [market_data_websocket.md](market_data_websocket.md)，盘中估值见 [live_valuation.md](live_valuation.md)。所有免费数据均为尽力而为、仅供研究、非交易级。

> 当前封板里程碑：**M04**。账本见 [accounting.md](accounting.md)，估值见 [account_valuation.md](account_valuation.md)，核对见 [account_reconciliation.md](account_reconciliation.md)，决策见 [ADR 0011](adr/0011-account-ledger-and-projections.md)。M04 仍无公开 Order/Fill 写 API、撮合、Broker 或实盘能力。

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

| 变更内容                        | 必读文档                                                                                  |
| ------------------------------- | ----------------------------------------------------------------------------------------- |
| 策略、信号、回测                | `domain_model.md`、`backtest_rules.md`、`risk_model.md`                                   |
| SC01 历史日线扫描器             | `scanners.md`、`market_data.md`、`database_schema.md`、ADR 0007–0008                     |
| N01 资讯与市场事件              | `information_center.md`、`database_schema.md`、`security.md`、ADR 0007                  |
| A01 AI 研究助手                 | `ai_research_assistant.md`、`information_event_center.md`、`database_schema.md`、`security.md` |
| 订单、成交、执行器              | `order_state_machine.md`、`reliable_messaging.md`、`risk_model.md`、`security.md`         |
| M05 手工订单、确认与本地 Outbox | `orders.md`、`order_confirmation.md`、`transactional_outbox.md`、ADR 0015–0016            |
| B01 模拟 Broker 与执行事实 | `simulated_broker.md`、`simulated_execution_pipeline.md`、`accounting.md`、`order_state_machine.md` |
| 数据库、事件、审计              | `database_schema.md`、`event_model.md`、`reliable_messaging.md`、ADR 0002、0004、0007     |
| Redis、队列、推送               | `reliable_messaging.md`、ADR 0003、0004                                                   |
| Web 或 API                      | `architecture.md`、`security.md`、`coding_standards.md`                                   |
| Broker 或行情适配器             | `architecture.md`、`risk_model.md`、ADR 0005                                              |
| 免费行情、Worker、实时推送      | `free_market_data.md`、`free_market_worker.md`、`market_data_websocket.md`、ADR 0012–0014 |
| 盘中估值                        | `live_valuation.md`、`account_valuation.md`、ADR 0011、0014                               |

若文档与实现发生冲突，先暂停变更并更新经评审的文档或 ADR；不得以临时实现绕过既定约束。

## M02 实现入口

- 本地启动和验收：根目录 `README.md`、`compose.yaml` 与 `scripts/`。
- FastAPI：`apps/api/src/alphadesk_api/`，依赖锁在 `apps/api/requirements.lock`。
- 纯领域模型：`apps/api/src/alphadesk_domain/`；SQLAlchemy 模型、仓储和 UoW：`apps/api/src/alphadesk_api/infrastructure/`。
- Migration：`apps/api/alembic/versions/0002_m02_domain_persistence.py`；完整表设计见 `database_schema.md`。
- React：`apps/web/src/`，依赖锁在 `apps/web/package-lock.json`。
- CI：`.github/workflows/ci.yml`。

M02 已建立 18 张核心领域/审计/Outbox 表。Redis 仍仅做连接检查，未建立 Streams、业务缓存、发布器或消费者。
