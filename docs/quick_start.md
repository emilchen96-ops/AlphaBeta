# AlphaDesk 快速开始

## 1. 启动系统

在仓库根目录执行：

```powershell
docker compose up --build -d
docker compose exec api alembic upgrade head
```

打开前端 <http://127.0.0.1:5173/>、“开始使用”
<http://127.0.0.1:5173/getting-started> 或 API 文档 <http://127.0.0.1:8000/docs>。

## 2. 一键准备研究环境

首次体验建议使用明确标记的本地 fixture：

```powershell
docker compose exec api python -m alphadesk_api.cli.demo initialize-research --mode fixture --json
docker compose exec api python -m alphadesk_api.cli.demo verify-research --json
```

完整本地复验可运行 `powershell -ExecutionPolicy Bypass -File scripts/check_u01.ps1`。

如果已经通过 D01 导入真实历史日线，可改用 `--mode existing-data`。该模式只读取本地数据库，
不会自动联网下载；数据不足时会给出下一步操作。

## 3. 推荐使用顺序

依次查看数据中心、自选行情、扫描运行、策略研究、批量研究、日线回测、历史回放、资讯事件、
AI 研究、风控决策、订单、成交和持仓。U01 演示中的 AI 是 Fake Provider，订单只进入本地
模拟 Broker，绝不连接真实券商。

### 第一次运行 Scanner

打开“条件扫描”，选择 `volume_anomaly` 或 `limit_up_pullback`、DAY_1 和研究标的后运行；
fixture 已预先生成两次可在“扫描运行”打开的结果。

### 第一次运行 Strategy

打开“策略”，选择 `sma_crossover`，短周期 2、长周期 3、数量 100。Strategy 只生成
Signal，不会创建订单。结果在“研究运行”和“研究 Signal”查看。

### 第一次运行 Backtest

打开“日线回测”，选择本地日线标的和 `sma_crossover`。回测使用独立账户，并按 T 日
收盘 Signal、下一有效交易日开盘执行。详情应包含指标、权益曲线、Order、Fill 和 Integrity。

### 第一次运行历史回放

打开“历史回放”，选择与回测相同的本地日线、策略和参数。建议先选 MANUAL：创建后点“单步”
逐日观察 Session、K 线、Signal、风控、订单、成交、账户和 Timeline；再用 X10 验证自动 Worker。
完成后检查最终指标与 Integrity。页面中的历史时间不是实时市场，回放不会连接 MiniQMT 或券商。

### 资讯、AI 与模拟订单

在“资讯中心”手工录入来源后，可从“AI 研究”选择事实运行 Fake 演示。AI 输出仅供研究。
若要启用真实 AI，按 [真实 AI Provider](real_ai_provider.md) 把 Provider、Base URL、Key 和模型
写入本地 `.env`，重新构建/启动 API，再先运行 `provider-status` 和 `test-provider`。不要把 Key
写入 `.env.example`、前端或浏览器请求。
在“订单”创建 U01-DEMO 的 LIMIT 订单，经过 R01 后人工确认，再从模拟执行入口提供本地
快照；成交可在“成交记录”，现金、持仓和对账可在“持仓”查看。

## 4. 状态和常见错误

- `READY`：当前代码、数据和配置满足使用条件。
- `NEEDS_DATA` / `NOT_READY`：前往数据中心补数，或运行 fixture 初始化。
- `NEEDS_CONFIG`：需要启用受支持 Provider；页面不会展示 Secret。
- `DEMO_ONLY`：仅 Fake AI 或明确演示数据，不代表生产可用。
- `DISABLED`：按安全基线关闭，例如实时行情。
- `NOT_IMPLEMENTED`：尚未开发，例如 MiniQMT。

若显示“无法连接 API”，先运行 `docker compose ps`，确认 API、PostgreSQL、Redis 均为
healthy；再访问 <http://127.0.0.1:8000/health/ready>。若页面仍旧，执行
`docker compose up --build -d` 后刷新。Correlation ID 可用于定位受控错误，但不要粘贴密码、
Token 或连接串。

当前不连接 MiniQMT，不是真实交易；AI 默认为 Disabled（U01 fixture 可显式使用 Fake），实时
行情默认为 Disabled。A01-P 已具备真实 AI Adapter，但是否可用取决于本地凭据与兼容服务。
