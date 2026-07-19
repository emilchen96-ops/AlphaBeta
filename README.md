# AlphaDesk

> **2026-07-19：I01 V0.1 集成基线已完成。** 当前功能、按钮、API、数据和配置状态以 [I01 集成说明](docs/integration_v0_1.md)、[功能盘点](docs/feature_inventory.md)、[UI 动作盘点](docs/ui_action_inventory.md)、[API 契约盘点](docs/api_contract_inventory.md) 与 [数据就绪度](docs/data_readiness.md) 为准。首页通过只读 `/api/v1/system/capabilities` 展示真实能力，不把“已实现”误报为“当前可运行”。下一步唯一主线是 **D01 历史行情数据中心**。

> SC01、N01、A01 已完成。BT01 独立提交因 Migration 与后续模块冲突，未并入当前稳定链；当前回测能力为 PARTIAL，需在 D01 后进入 BT01-R。系统仍无 Windows 执行器、MiniQMT、外部 Broker 或实盘能力。

> A01 文档：[AI 研究助手](docs/ai_research_assistant.md)；N01 文档：[资讯事件中心](docs/information_event_center.md)；SC01 文档：[历史条件扫描器](docs/scanners.md)。

> N01 已实现 AI 之前的资讯事实层：手工文本、RSS/Atom Adapter、RawDocument 原文保留、Hash/external ID 去重、InformationItem、MarketEvent、Instrument/主题关联、API、CLI 和资讯页面。系统尚未进行 AI 分析，不验证全部外部事实，也不会创建订单。详见 [N01 资讯事件中心](docs/information_center.md)。

> SC01 已实现 A 股历史日线条件扫描器：统一纯 Python Scanner 契约、成交量异常与涨停后回踩近似规则、ScanRun/ScanResult 持久化、API、CLI 和 `/scanners`、`/scan-runs` 页面。扫描结果仅是历史规则筛选，不代表投资建议，不是实时扫描，也不会创建 Signal 或订单。详见 [SC01 扫描器](docs/scanners.md)。

> M05 已完成本地订单事实管道：模拟账户手工创建、人工确认、取消、过期、查询/Timeline、`SUBMIT_ORDER/PENDING` 与 Transactional Outbox 原子写入，以及 `/orders` 网页。QUEUED 不是已发送，Outbox PENDING 不是已发布；没有 Broker、Executor、Fill、资金/组合风控或实盘。详见 [订单](docs/orders.md)、[人工确认](docs/order_confirmation.md) 与 [Outbox](docs/transactional_outbox.md)。

> M04.1A 已加入默认禁用的免费真实行情基础设施：BaoStock 历史行情、AKShare/EastMoney 快照与近期 1 分钟线、独立单 Leader Worker、Redis 最新报价、版本化 WebSocket 和只读盘中估值。全部免费数据仅供研究、非交易级；没有新增下单、撮合、Broker 或实盘能力。

> M04 已加入本地模拟账户、资金/持仓只追加账本、成交记账、行情估值、账本核对与 `/portfolio` 网页。它不包含公开订单/成交写 API、撮合、Broker 或实盘。详见 [账本](docs/accounting.md)、[估值](docs/account_valuation.md) 和 [核对](docs/account_reconciliation.md)。

当前封板里程碑为 M03：项目提供离线确定性的 DEMO 行情、受限本地 CSV 导入、标的目录、自选股与网页行情工作台。真实外部行情入口默认禁用；系统没有策略、Signal、订单、Broker 或实盘能力。详见 [M03 行情文档](docs/market_data.md) 与 [自选股规则](docs/watchlists.md)。

AlphaDesk 是一个面向个人使用的本地量化交易系统。项目以可审计、可恢复和安全边界清晰为首要目标，当前采用 React + TypeScript 前端、FastAPI 模块化单体后端、PostgreSQL 与 Redis 基础设施。

## 当前阶段：M02

M00 架构规则、M01 项目骨架和 M02 领域持久化已经完成。当前具备：

- 中文 React 管理后台、响应式侧栏、路由和明确的空页面；
- FastAPI 应用工厂、统一配置、结构化日志和 Correlation ID；
- 存活、就绪、系统状态接口及仅用于展示连接的 WebSocket；
- 纯 Python 领域实体/协议，以及独立的 SQLAlchemy 模型、仓储和 Unit of Work；
- 18 张 PostgreSQL 核心领域、审计与 Outbox 表和可逆 Alembic Migration；
- Redis 异步客户端（仍仅用于依赖探测，尚无 Streams）；
- PostgreSQL、Redis、API、Web 的本地 Docker Compose 编排；
- 后端与前端自动化测试、静态检查、依赖锁文件和基础 CI。

M04.1A market infrastructure is sealed: BaoStock historical data is available, while the real-time provider is disabled after AKShare validation failed. Redis, WebSocket, and UI plumbing remain for a later Windows Agent/MiniQMT integration. Historical closes are not real-time prices; the system has no real-trading capability and must not be publicly deployed.

> 该系统目前只能用于本地开发，禁止部署到公网。

## 本地环境要求

- 推荐：Docker Desktop（包含 Docker Compose）；
- Windows PowerShell 5.1 或 PowerShell 7；
- 仅在不使用容器运行检查时需要 Python 3.12 和 Node.js 22/npm。

## Windows 启动

1. 可选：复制 `.env.example` 为 `.env`，并修改其中仅供本地使用的占位密码。
2. 在仓库根目录运行 `./scripts/dev.ps1`。
3. 查看状态运行 `./scripts/dev.ps1 -Action status`。
4. 停止服务运行 `./scripts/stop.ps1`。

脚本失败时会返回非零退出码。停止脚本默认保留 PostgreSQL 和 Redis 数据卷。

## Docker Compose 启动

```text
docker compose config
docker compose up --build -d
docker compose ps
```

默认访问地址：

- 网页：http://localhost:5173
- API：http://localhost:8000
- API 文档：http://localhost:8000/docs
- 行情 WebSocket：ws://localhost:8000/ws/v1/market-data

M04.1A 完整工程验收运行 `./scripts/check_m04_1.ps1`；真实免费源连接仅在显式运行 `./scripts/check_m04_1_external.ps1` 时检查，不属于默认 CI。

端口可通过 `.env` 中的 `WEB_PORT` 和 `API_PORT` 调整。PostgreSQL 和 Redis 默认不映射到宿主机端口，只在 Compose 网络内使用。

## 手工检查

```text
GET http://localhost:8000/health/live
GET http://localhost:8000/health/ready
GET http://localhost:8000/api/v1/system/status
WS  ws://localhost:8000/ws/system
```

WebSocket 只接受用于连接验证的 `ping` 并返回 `pong`，不承载任何交易指令。打开网页后，应能切换左侧页面，并在总览查看 API、PostgreSQL、Redis 与 WebSocket 的真实状态。

## 自动测试与质量检查

Windows 一键检查：

```text
./scripts/check.ps1
```

容器内后端检查：

```text
docker compose run --rm api sh -c "ruff check . && ruff format --check . && mypy src && pytest"
```

容器内前端检查：

```text
docker compose run --rm web sh -c "npm run lint && npm run typecheck && npm run test && npm run build"
```

迁移检查：

```text
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

## 常见故障

- `docker` 命令不存在：安装并启动 Docker Desktop，然后重新打开终端。
- API 未就绪：运行 `docker compose ps`，检查 PostgreSQL、Redis 是否 healthy。
- 网页显示 API 离线：确认 8000 端口未被占用，并检查 `VITE_API_BASE_URL`。
- 配置解析失败：对照 `.env.example` 检查 JSON 列表、布尔值和端口格式。
- 依赖状态在恢复后未立即更新：等待自动刷新或点击“刷新状态”；WebSocket 使用有上限的退避间隔重连。

## 数据卷清理警告

`docker compose down` 会停止容器但保留数据。`docker compose down -v` 会永久删除本项目的 PostgreSQL 和 Redis 命名卷；执行前必须确认没有需要保留的本地数据。

## 安全边界

- `.env` 已被 Git 忽略，仓库只提供本地占位配置；
- 只有 `VITE_` 前缀的非敏感值可进入前端；
- 前端不持有数据库、Redis 或未来券商凭据；
- 当前没有认证能力，不得暴露在不可信网络；
- 当前仅有 PostgreSQL 中的模拟账户和本地确定性模拟成交；没有真实券商接入、MiniQMT 或实盘交易能力。

## B01 本地模拟 Broker

经过 R01 风控和 M05 人工确认的订单，可在订单中心显式输入测试市场快照并执行本地模拟成交。结果会写入 Attempt、Fill 和 M04 模拟账本；成交记录页面只读展示费用及现金影响。完整操作说明见 [B01-C 模拟执行界面](docs/simulated_broker_ui.md)。该能力不读取真实行情、不连接券商，也不会产生真实交易。

完整文档从 [docs/index.md](docs/index.md) 开始；开发任务必须遵守 [AGENTS.md](AGENTS.md)。

## SC01 历史日线条件扫描

启动 API、PostgreSQL 和 Web 后访问 `http://localhost:5173/scanners`。先确保目标 Instrument 已有本地 `DAY_1` 历史 K 线，再选择扫描器、股票池、截止时间和参数运行；结果可在 `/scan-runs` 查询。该功能不会调用风控、Broker 或账本，也不会产生订单。

## N01 资讯事件中心

访问 `http://localhost:5173/information` 可手工录入带来源、发布时间、Instrument 和主题的资讯；`/market-events` 查询确定性事件事实。原始正文保留且不会被规范化内容覆盖，发布时间和接收时间分别展示。

## M01.1 端到端补充验收

M01 基础设施已于 2026-07-15 在 Docker Desktop 29.6.1、Docker Compose 5.3.0 上完成真实四服务验收：PostgreSQL、Redis、API、Web 均通过健康检查；在线 Alembic 版本为 `0001_m01_bootstrap`；后端 16 项测试（含真实 PostgreSQL/Redis 集成测试）和前端 12 项测试全部通过。

验收还覆盖了 PostgreSQL、Redis、API 分别中断后的降级与恢复，以及整组 Compose 重启后的命名卷持久性。全部服务在线的浏览器截图保存在 [`outputs/m01-1-all-services-online.png`](outputs/m01-1-all-services-online.png)。该结论只确认 M01 工程基础设施，不代表任何交易业务或实盘能力已实现。

## 当前阶段：M02

M02 已完成纯 Python 领域模型、18 张 PostgreSQL 核心表、SQLAlchemy 映射、异步仓储和 Unit of Work。完整结构见 [数据库模型](docs/database_schema.md)，架构决定见 [ADR 0007](docs/adr/0007-domain-persistence-separation.md)。现有网页和公开 API 未增加交易功能。

M02 一键验收会启动独立的临时测试数据库并执行迁移往返、约束、事务和前后端回归：

```text
./scripts/check_m02.ps1
```

若 Windows 的本机执行策略禁止直接运行脚本，可仅为本次进程使用：

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_m02.ps1
```

测试数据库必须通过 `ALPHADESK_TEST_DATABASE_URL` 明确配置且库名包含 `test`。M02 尚未实现 Outbox 发布器、Redis Streams、业务 API、订单状态机执行、风控、Broker、MiniQMT/XtQuant 或实盘能力；下一阶段 M03 仅负责事件与 Transactional Outbox 发布链路。
