# I01 功能盘点矩阵

> U01 新增一键研究初始化、只读研究验收、系统能力卡片和 `/getting-started`。这些能力只编排
> 已有模块；不新增真实行情、真实 AI、MiniQMT 或实盘交易能力。

基线：`codex/integration-v0.1`，来源提交 `6d3aec6`。状态由代码、OpenAPI、前端接线、定向测试和 2026-07-19 隔离数据库检查共同确定，不以路线文档中的旧描述替代实现证据。

统计口径已随 D01 与 BT01-R 更新；模块状态以当前代码、OpenAPI、页面接线和 2026-07-20 验收结果为准。

| 模块 | 页面 | 用户操作 | 前端方法 | HTTP 接口 | 应用服务 | 数据依赖 | 配置依赖 | 状态 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 首页 | `/` | 刷新基础设施与能力状态 | `fetchSystemStatus`、`fetchSystemCapabilities` | `GET /system/status`、`GET /system/capabilities` | 依赖探测、`assess_system_capabilities` | 无业务数据 | API/DB/Redis | WORKING | 能区分实现、数据、配置与当前可用性。 |
| 行情与数据源 | `/market` | 标的查询、自选股维护、K 线查询 | `market.ts` | `/instruments`、`/watchlists`、`/market-data/*` | Market query/watchlist services | Instrument、MarketBar | 外部同步默认关闭 | NEEDS_DATA | 页面与接口可用；当前验收库 Instrument/MarketBar 均为 0。 |
| Portfolio | `/portfolio` | 创建模拟账户、入出金、估值、核对 | `accounts.ts` | `/accounts/*` | Accounting、valuation、reconciliation services | 模拟账户、行情 | 无外部 Broker | NEEDS_DATA | 代码可用；当前验收库无模拟账户。 |
| Orders | `/orders` | 创建、确认、取消、查看 Timeline | `orders.ts` | `/orders/*` | M05 order services + R01 gate | 模拟账户、Instrument | 风控配置 | NEEDS_DATA | 无账户/标的时不能形成订单事实。 |
| Risk | `/risk/decisions`、`/risk/limits` | 查询决策、查看限制、Signal 风险评估 | `risk.ts` | `/risk-decisions*`、`/risk-limits/active`、`/signals/{id}/risk-assessments` | RiskDecision services | 账户、标的、可选 Signal | R01 阈值 | NEEDS_DATA | 当前无 RiskDecision；限制查询本身可用。 |
| Simulated Broker | `/orders`、`/fills` | 对已确认订单输入手工快照并模拟执行 | `orders.ts` | `/orders/{id}/simulated-executions`、`/fills*` | SimulatedExecutionService、FillAccountingService | 可执行订单、账户 | 本地模拟费用/滑点模型 | NEEDS_DATA | 代码已实现；当前没有可执行订单。 |
| Strategies | `/strategies` | 查看目录并创建历史研究 | `strategies.ts` | `/strategies/catalog*`、`POST /strategy-runs` | StrategyRunner | Instrument、历史 K 线 | 无 | NEEDS_DATA | 策略目录可加载，运行缺行情。 |
| Strategy Runs | `/strategy-runs*` | 查询运行、详情与 Signal | `strategies.ts` | `/strategy-runs*` | StrategyRunQueryService | StrategyRun | 无 | NEEDS_DATA | 当前运行数为 0。 |
| Signals | `/signals` | 查询 Signal、独立风险评估 | `strategies.ts`、`risk.ts` | `GET /signals`、`POST /signals/{id}/risk-assessments` | Signal query、RiskDecision | StrategyRun/Signal、账户 | R01 阈值 | NEEDS_DATA | Signal 不会自动转订单。 |
| Strategy Experiments | `/strategy-experiments*` | 参数网格、同步批量运行、比较 | `strategies.ts` | `/strategy-experiments*` | StrategyExperimentService | Instrument、历史 K 线 | 组合上限 50 | NEEDS_DATA | 接口和页面存在，当前无可运行行情。 |
| Scanner | `/scanners`、`/scan-runs*` | 目录、创建运行、结果与完整性 | `scanners.ts` | `/scanners/catalog`、`/scan-runs*` | ScannerRunService | Instrument、足够历史日线 | 无 | NEEDS_DATA | 两个规则已注册；当前无行情。 |
| Information Center | `/information*` | 手工录入、查询、查看来源事实 | `information.ts` | `/information-sources`、`/information/manual`、`/information-items*` | InformationIngestionService | PostgreSQL | RSS 手工摄取需来源 URL | WORKING | 手工录入不依赖预置行情；验收库有 2 条。 |
| Market Events | `/market-events*` | 查询和查看确定性事件 | `information.ts` | `/market-events*` | Information query | InformationItem/MarketEvent | 无 | WORKING | 验收库有 2 条事件。 |
| AI Research | `/ai-research`、`/ai-analyses*`、`/research-insights*` | 创建研究、查看 Evidence | `aiResearch.ts` | `/ai/providers/status`、`/ai/analyses*`、`/research-insights*` | AIResearchAnalysisService | InformationItem/MarketEvent | 默认 Provider=`disabled` | NEEDS_CONFIG | Fake 可验收；真实 Provider 未实现。Provider 禁用时按钮已禁用。 |
| Backtests | `/backtest`、`/backtest/:id` | 创建同步日线回测并查看全部事实与 Integrity | `backtests.ts` | `POST/GET /backtests*` | `BacktestRunService`、Performance、Integrity | D01 权威日线 | 回测规模/风控配置 | NEEDS_DATA | BT01-R 已完成；没有满足所选范围的本地日线时明确拒绝，不会访问网络补数。 |
| Audit | `/audit` | 只读查看计划状态 | 无 | 无统一审计查询 API | 部分模块会写 AuditLog | AuditLog/DomainEvent | 无 | PLACEHOLDER | 不伪装为可查询审计中心。 |
| Settings | `/settings` | 只读查看说明 | 无保存方法 | 无设置写 API | 无 | 无 | 服务端环境变量 | PLACEHOLDER | 没有可编辑或无响应的保存按钮。 |
| Realtime Market Data | `/market` | 查看实时状态/Quote/WebSocket | `market.ts`、`marketDataWebSocket.ts` | `/market-data/realtime/*`、`/ws/v1/market-data` | Redis Quote/WS plumbing | Redis 临时 Quote | Provider 固定 disabled | NEEDS_CONFIG | 管道保留但没有已批准实时源，非交易级。 |
| MiniQMT | 无 | 无 | 无 | 无 | 无 Windows Agent/Adapter | 不适用 | 不适用 | NOT_IMPLEMENTED | 不应暴露真实下单入口。 |

## CLI 盘点

| CLI 模块 | 命令 |
| --- | --- |
| `alphadesk_api.cli.market_data` | `provider-check`、`fetch-free-quotes`、`free-market-status`、`free-market-run-once`、`seed-demo`、`sync-instruments`、`sync-bars`、`import-csv`、`sync-daily`、`sync-recent-minute-bars`、`sync-status` |
| `alphadesk_api.cli.accounting` | `create-demo-account`、`deposit`、`seed-demo-portfolio`、`apply-fill`、估值/核对查询命令 |
| `alphadesk_api.cli.orders` | `create-demo-orders`、`list`、确认/取消类命令、`expire-pending`、`verify-integrity` |
| `alphadesk_api.cli.simulated_broker` | `execute`、尝试/成交/完整性查询、`run-demo` |
| `alphadesk_api.cli.scanners` | `run`、`list`、详情/结果/完整性查询 |
| `alphadesk_api.cli.information` | `add-manual`、`ingest-rss`、`list`、`verify-integrity` |
| `alphadesk_api.cli.ai` | `provider-status`、`analyze`、`list`、`show`、`verify-integrity` |
| `alphadesk_api.cli.backtests` | `run`、`list`、`show`、`metrics`、`verify-integrity`、`run-demo` |

当前没有统一 Strategy CLI、Audit CLI、Settings CLI、Windows Agent 或 MiniQMT CLI。
