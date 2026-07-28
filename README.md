# AlphaDesk

> **UX02-B 研究工作台：** 默认产品模式为 `RESEARCH_ONLY`。推荐从
> `http://127.0.0.1:5173/research/backtest` 用自然语言或模板确认安全规则，再调用完整
> BT01 历史模拟；回测不会向 MiniQMT 或券商发送订单。详见
> [快速回测工作流](docs/quick_backtest_workflow.md)。

> **2026-07-23：MD01 MiniQMT 单一行情源完成。** 正式环境的 A 股/ETF 目录、实时快照、
> 历史日线和历史分钟线均来自 MiniQMT。Windows 只读 Agent 负责连接 XtQuant，Redis 与
> WebSocket 承载实时展示，PostgreSQL 保存可追溯的历史 K 线。BaoStock、AKShare、东方财富、
> 本地文件和测试数据只保留为显式测试能力，不会进入正式查询，也不会作为故障回退源。

> 行情相关页面现统一为“行情”和“数据中心”。旧 `/miniqmt-market-data` 会跳转到“行情”，
> 旧 `/intraday-market-data` 会跳转到“数据中心/分钟行情”。完整启动、数据流、页面操作与
> 故障排查见 [MD01 行情使用说明](docs/md01_market_data.md)。

> **安全边界：** 当前 MiniQMT 接入只导入 `xtquant.xtdata`。它不读取券商账户、资金、持仓、
> 委托或成交，不导入交易 SDK，也不能下单或撤单。AlphaDesk 中已有的订单、回测和模拟账本
> 能力不会通过该行情 Agent 发送到券商。

AlphaDesk 是一个面向个人使用的本地量化交易系统。项目以可审计、可恢复和安全边界清晰为首要目标，当前采用 React + TypeScript 前端、FastAPI 模块化单体后端、PostgreSQL 与 Redis 基础设施。

## MiniQMT 行情日常操作

先启动并登录 MiniQMT 行情入口，再启动 AlphaDesk 基础服务和 Windows 只读 Agent：

```powershell
docker compose up --build -d postgres redis api web
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt run-agent
```

打开 <http://127.0.0.1:5173/market> 搜索、自选、查看实时报价和 K 线；打开
<http://127.0.0.1:5173/market-data-center> 查看目录、日线、分钟线、覆盖度和质量。
历史数据缺失时只会明确提示并提供 MiniQMT 补数操作，不会显示演示 K 线。

## BT01 日线回测

启动服务并完成 D01 本地日线补数后，打开 `http://127.0.0.1:5173/backtest`。创建操作为同步执行，T 日收盘信号最早在下一根可用日线开盘成交。也可在 API 容器或已激活的后端环境运行：

```powershell
python -m alphadesk_api.cli.backtests run-demo
python -m alphadesk_api.cli.backtests list
```

`run-demo` 只读取或建立明确标识的本地确定性 Demo 行情，不访问外部网络，也不会发送真实订单。

## RT01 日线历史回放

启动完整 compose 后打开 `http://127.0.0.1:5173/replays`。MANUAL 可逐日单步，X1/X10/X100
由独立 `replay_worker` 推进；倍速只影响等待时间，不改变业务结果。也可运行：

```powershell
docker compose exec api python -m alphadesk_api.cli.replays run-demo
docker compose exec api python -m alphadesk_api.cli.replays list
```

## 基础工程：M01-M02

M00 架构规则、M01 项目骨架和 M02 领域持久化已经完成，并作为后续模块的基础：

- 中文 React 管理后台、响应式侧栏、路由和明确的空页面；
- FastAPI 应用工厂、统一配置、结构化日志和 Correlation ID；
- 存活、就绪、系统状态接口及仅用于展示连接的 WebSocket；
- 纯 Python 领域实体/协议，以及独立的 SQLAlchemy 模型、仓储和 Unit of Work；
- 18 张 PostgreSQL 核心领域、审计与 Outbox 表和可逆 Alembic Migration；
- Redis 异步客户端（仍仅用于依赖探测，尚无 Streams）；
- PostgreSQL、Redis、API、Web 的本地 Docker Compose 编排；
- 后端与前端自动化测试、静态检查、依赖锁文件和基础 CI。

MD01 已将 MiniQMT 设为唯一正式行情源。历史兼容适配器仍可用于测试，但正式查询不会读取或
回退到这些来源。MiniQMT 行情连接不等于交易连接，系统仍无 MiniQMT 实盘下单能力。

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
- 当前仅有 PostgreSQL 中的模拟账户和本地确定性模拟成交；MiniQMT 仅提供只读行情，
  没有真实券商交易接入或实盘交易能力。

## B01 本地模拟 Broker

经过 R01 风控和 M05 人工确认的订单，可在订单中心显式输入测试市场快照并执行本地模拟成交。结果会写入 Attempt、Fill 和 M04 模拟账本；成交记录页面只读展示费用及现金影响。完整操作说明见 [B01-C 模拟执行界面](docs/simulated_broker_ui.md)。该能力不读取真实行情、不连接券商，也不会产生真实交易。

第一次使用请阅读图文版 [AlphaDesk 使用指南](docs/user_guide.md)；完整开发文档从 [docs/index.md](docs/index.md) 开始，开发任务必须遵守 [AGENTS.md](AGENTS.md)。

## 历史行情

正式环境只通过 MiniQMT Agent 补充历史日线和 1 分钟线。推荐在“行情”或“数据中心”选择
明确股票和日期范围，也可使用只读 CLI：

```text
python -m alphadesk_api.cli.miniqmt backfill-history --instrument <UUID> --timeframe DAY_1 --start <含时区时间> --end <含时区时间>
```

BaoStock、AKShare、东方财富和 Fixture 适配器仅保留给显式测试环境，不应作为日常补数命令，
也不会在 MiniQMT 断开时自动启用。所有补数都不会创建 Signal、订单、成交或账本事实。

## SC02-A MiniQMT 全 A 股标准条件选股

启动 PostgreSQL、Redis、API、`scanner_worker`、Web 和 Windows MiniQMT 只读行情
Agent 后，访问 `http://localhost:5173/scanners`。选择“涨停回踩”或“底部放倍量”
模板和筛选日期即可创建后台任务。系统按历史点时解析沪深北全部 A 股，批量读取本地
MiniQMT 日线，展示进度、统计、结果和中文入选原因。首次全市场数据准备可能耗时
较长；数据不足会明确计数，不会伪装为全市场成功。扫描不会调用风控、Broker、账本
或 MiniQMT 交易接口，也不会产生 Signal 或订单。完整说明见
[SC02-A 选股引擎](docs/sc02_screening_engine.md)；旧 SC01-R 补数链路见
[扫描器说明](docs/scanners.md)。

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
