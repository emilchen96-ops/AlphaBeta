# AlphaDesk

AlphaDesk 是一个面向个人使用的本地量化交易系统。项目以可审计、可恢复和安全边界清晰为首要目标，当前采用 React + TypeScript 前端、FastAPI 模块化单体后端、PostgreSQL 与 Redis 基础设施。

## 当前阶段：M01

M00 架构规则与 M01 项目骨架已经完成。当前具备：

- 中文 React 管理后台、响应式侧栏、路由和明确的空页面；
- FastAPI 应用工厂、统一配置、结构化日志和 Correlation ID；
- 存活、就绪、系统状态接口及仅用于展示连接的 WebSocket；
- SQLAlchemy 异步连接基础、Redis 异步客户端和空 Alembic bootstrap 迁移；
- PostgreSQL、Redis、API、Web 的本地 Docker Compose 编排；
- 后端与前端自动化测试、静态检查、依赖锁文件和基础 CI。

当前**不具备**行情、账户、持仓、策略、信号、风控、订单、成交、模拟 Broker、MiniQMT/XtQuant、AI 或真实交易能力。M01 也没有用户认证、登录或权限系统。

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
- 当前没有账户、券商接入或实盘交易能力。

完整文档从 [docs/index.md](docs/index.md) 开始；开发任务必须遵守 [AGENTS.md](AGENTS.md)。下一阶段 M02 的范围仅是领域模型与 PostgreSQL 持久化，尚未实施。

## M01.1 端到端补充验收

M01 基础设施已于 2026-07-15 在 Docker Desktop 29.6.1、Docker Compose 5.3.0 上完成真实四服务验收：PostgreSQL、Redis、API、Web 均通过健康检查；在线 Alembic 版本为 `0001_m01_bootstrap`；后端 16 项测试（含真实 PostgreSQL/Redis 集成测试）和前端 12 项测试全部通过。

验收还覆盖了 PostgreSQL、Redis、API 分别中断后的降级与恢复，以及整组 Compose 重启后的命名卷持久性。全部服务在线的浏览器截图保存在 [`outputs/m01-1-all-services-online.png`](outputs/m01-1-all-services-online.png)。该结论只确认 M01 工程基础设施，不代表任何交易业务或实盘能力已实现。
