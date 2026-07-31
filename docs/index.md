# AlphaDesk 文档索引

> 当前行情里程碑为 **MD01 MiniQMT 单一正式行情源**：日常启动、统一行情页面、数据中心和
> 故障排查见 [MD01 行情使用说明](md01_market_data.md)。底层能力边界与数据链路见
> [MiniQMT 只读行情](miniqmt_readonly_market_data.md)，期望/实际订阅见
> [行情订阅模型](market_subscription_model.md)，Windows 进程与启动方式见
> [MiniQMT 行情代理](miniqmt_market_data_agent.md)。该能力不读取账户、资金、持仓、委托或
> 成交，不提供下单和撤单。

> UX01 前端中文化、业务可读性、内部编号降噪和关键交互规范见
> [前端可读性规范](ux_conventions.md)。该整改不改变 API、数据库或交易安全边界。

> UX02 默认研究模式、六入口任务式导航、策略研究统一入口与 MiniQMT 回测数据源规则见
> [研究模式与任务式导航](ux02_research_mode.md)。

## D02 市场数据语义

- [A 股交易日历](trading_calendar.md)
- [CAL01-R 日历与智能选股窗口语义](cal01r_calendar_screening_semantics.md)
- [复权因子与 QFQ](adjustment_factors.md)
- [停复牌与 Instrument 生命周期](suspension_and_lifecycle.md)
- [市场价格语义](market_price_semantics.md)

> 当前回放里程碑为 **RT01 完成**：总览见 [历史日线回放](historical_replay.md)，控制与恢复见
> [回放控制模型](replay_control_model.md)，Worker 见 [Replay Worker](replay_worker.md)，页面见
> [回放页面](replay_ui.md)。仅使用 D01 历史日线，不连接 MiniQMT 或券商。下一阶段仅为 D02。

> 当前 AI 增量里程碑为 **A01-P 完成**：真实 OpenAI 兼容 Adapter、Secret 配置、连通状态、
> Prompt/Schema/Evidence 边界、usage 与成本见 [真实 AI Provider](real_ai_provider.md) 和
> [AI 研究助手](ai_research_assistant.md)。默认 Disabled；外部凭据未联调。其后 RT01 已完成。

> U01 使用入口：[快速开始](quick_start.md)、[演示研究环境](demo_research_environment.md)、
> [系统能力状态](system_capabilities.md) 与 [可用性收口状态](usability_status.md)。

> 第一次使用请先阅读 [AlphaDesk 使用指南](user_guide.md)：包含开机启动、首次数据准备、菜单与按钮说明、推荐业务流程、真实页面截图和常见故障排查。

> 当前回测里程碑为 **BT01-R 完成**：日线回测总览见 [daily_backtest.md](daily_backtest.md)，严格时间边界见 [backtest_time_model.md](backtest_time_model.md)，指标口径见 [backtest_metrics.md](backtest_metrics.md)，页面见 [backtest_ui.md](backtest_ui.md)，决策见 [ADR 0017](adr/0017-deterministic-daily-backtest-pipeline.md)。分钟回测尚未完成，下一阶段仅为 U01。

> 数据里程碑 **D01 已完成**：BaoStock A 股 Instrument/研究池、历史补数、每日增量、质量事实、覆盖率、Readiness、API/CLI 和数据中心页面见 [D01 历史行情](historical_market_data.md)、[每日增量](daily_market_data_update.md)、[质量检查](market_data_quality.md) 与 [数据中心页面](market_data_center_ui.md)。D01 本身不包含实时行情、MiniQMT 或交易写入；其历史日线现已被 BT01-R 使用。

> **I01 V0.1 集成基线已完成**。盘点见 [集成说明](integration_v0_1.md)、[功能盘点](feature_inventory.md)、[UI 动作盘点](ui_action_inventory.md)、[API 契约盘点](api_contract_inventory.md) 与 [数据就绪度](data_readiness.md)；相关状态已随 D01 和 BT01-R 更新。

> 当前研究基线为 **A01 + A01-P 完成**：版本化 Prompt、Disabled/Fake/真实兼容 Provider、AIAnalysisRun、ResearchInsight、Evidence、API、CLI 和页面见 [ai_research_assistant.md](ai_research_assistant.md)。真实 Provider 默认禁用且依赖本地凭据；AI 输出仅供研究，不创建 Signal 或订单。

> 当前资讯里程碑为 **N01 完成**：手工/RSS 来源、RawDocument、规范化与去重、MarketEvent、Instrument/主题关联、API、CLI 和页面见 [information_center.md](information_center.md)。当前尚未经过 AI 分析，不构成投资建议，不创建订单。

> 当前研究工具里程碑为 **SC03-A 完成开发**：标准条件目录、安全 ScreeningSpec、历史点时
> 全 A 股股票池、批量规则引擎和两个标准形态见
> [SC02-A 选股引擎](sc02_screening_engine.md)；确定性中文解析、可选 AI 辅助、中文预览
> 和 Schema 驱动编辑器见
> [SC02-B 自然语言选股](sc02_natural_language_screening.md)。
> SC02-C 进一步提供 [智能选股模板](screening_templates.md)、
> [我的选股方案](user_screening_definitions.md)、[历史结果](screening_history.md)、
> [加入自选](screening_to_watchlist.md)和[快速回测接线](screening_to_backtest.md)。
> SC02-D 增加 [选股数据自动准备与运行编排](sc02_screening_data_preparation.md)：
> 点击开始后自动规划交易日窗口、检查本地覆盖、只补 MiniQMT 缺失区间、复检质量、
> 预热所需特征，再调用原 SC02 引擎；普通用户不再需要先去数据中心手工补数。
> SC03-A 增加 [可搜索原子条件与组合编辑器](sc03_atomic_condition_builder.md)：
> 中文别名搜索、参数化条件积木、AND/OR 条件树、v1 兼容和逐原子结果审计。
> SC01-R 后台补数与旧接口继续兼容，见 [扫描器说明](scanners.md)。结果不会创建 Signal
> 或订单。

> 当前执行里程碑为 **B01 完成开发，等待最终环境验收**：B01-A Broker 契约与确定性计算见
> [simulated_broker.md](simulated_broker.md)；B01-B Attempt、Fill、M04 原子记账、Command 消费和
> Outbox 抑制见 [simulated_execution_pipeline.md](simulated_execution_pipeline.md)；B01-C API、CLI、Demo
> 与网页见 [simulated_broker_ui.md](simulated_broker_ui.md)。系统仍无 Windows 执行器、MiniQMT、外部
> Broker 或实盘能力；下一阶段仅规划 BT01 日线回测。

> 当前风险里程碑为 **R01 完成**：纯规则核心见 [risk_engine.md](risk_engine.md)，快照、持久化、幂等、查询和 M05 安全门见 [risk_decision_pipeline.md](risk_decision_pipeline.md)，只读页面和关联边界见 [risk_ui.md](risk_ui.md)。下一阶段为 B01 模拟 Broker；系统仍无执行器、MiniQMT 或实盘能力。


> 当前数据里程碑为 **D03 完成**：历史分钟 Provider、时间模型、聚合、质量、Readiness、
> API/CLI 与页面见 [intraday_market_data.md](intraday_market_data.md)、
> [intraday_time_model.md](intraday_time_model.md)、[intraday_aggregation.md](intraday_aggregation.md)、
> [intraday_data_quality.md](intraday_data_quality.md) 和 [intraday_data_ui.md](intraday_data_ui.md)。

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

> TA01 已建立 [多智能体 AI 调研工作台](ai_research_workbench.md)、
> [角色与持久化流程](ai_multi_agent_workflow.md)、[模型服务配置](ai_provider_configuration.md)
> 和 [结构化报告 Schema](ai_report_schema.md)。其运行时不依赖 TradingAgents 目录，且不具备任何交易能力。

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
| UX03-R 研究档案与批量总报告     | `ux03_research_archive.md`、`backtest_rules.md`、`backtest_ui.md`                         |
| UX02-B 研究工作台               | `research_product_mode.md`、`strategy_spec.md`、`natural_language_strategy.md`、`visual_strategy_editor.md`、`quick_backtest_workflow.md` |
| BT01 A 股日线回测               | `daily_backtest.md`、`backtest_time_model.md`、`backtest_metrics.md`、`backtest_ui.md`、ADR 0017 |
| RT01 日线历史回放               | `historical_replay.md`、`replay_control_model.md`、`replay_worker.md`、`replay_ui.md` |
| D01 A 股历史日线                | `historical_market_data.md`、`daily_market_data_update.md`、`market_data_quality.md`、`market_data_center_ui.md`、`data_readiness.md` |
| D03 A 股历史分钟数据            | `intraday_market_data.md`、`intraday_time_model.md`、`intraday_aggregation.md`、`intraday_data_quality.md`、`intraday_data_ui.md` |
| L2.5-A MiniQMT 只读行情         | `miniqmt_readonly_market_data.md`、`market_subscription_model.md`、`miniqmt_market_data_agent.md`、`market_data_websocket.md` |
| SC02/SC03 标准条件选股闭环      | `sc02_screening_engine.md`、`sc02_natural_language_screening.md`、`sc02_screening_data_preparation.md`、`sc03_atomic_condition_builder.md`、`screening_templates.md`、`user_screening_definitions.md`、`screening_history.md`、`screening_to_watchlist.md`、`screening_to_backtest.md` |
| N01 资讯与市场事件              | `information_center.md`、`database_schema.md`、`security.md`、ADR 0007                  |
| A01/TA01 AI 调研               | `ai_research_workbench.md`、`ai_multi_agent_workflow.md`、`ai_provider_configuration.md`、`ai_report_schema.md`、`ai_research_assistant.md`、`real_ai_provider.md`、`database_schema.md`、`security.md` |
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
