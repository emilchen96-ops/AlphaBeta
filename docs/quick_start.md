# AlphaDesk 快速开始

## D02 市场参考数据

完成 D01 日线后，在“历史行情数据中心”依次 Dry-run 并同步交易日历、复权因子、停复牌和生命周期，再查看 QFQ Readiness。CLI 等价命令：

```powershell
python -m alphadesk_api.cli.market_reference sync-calendar --provider fixture
python -m alphadesk_api.cli.market_reference sync-adjustments --provider fixture --max-instruments 30
python -m alphadesk_api.cli.market_reference sync-suspensions --provider fixture --max-instruments 30
python -m alphadesk_api.cli.market_reference sync-instrument-lifecycle --provider fixture --max-instruments 30
python -m alphadesk_api.cli.market_reference verify
```

Fixture 不访问网络。只有显式启用 Tushare 且从环境变量提供 Token 后才可做真实 Provider 联调。

## 1. 启动系统

在仓库根目录执行：

```powershell
docker compose up --build -d
docker compose exec api alembic upgrade head
```

打开前端 <http://127.0.0.1:5173/> 或 API 文档 <http://127.0.0.1:8000/docs>。
“开始使用”和数据中心已归入“设置”的帮助与高级入口。

### 启动 MiniQMT 只读行情

先启动并登录 Windows MiniQMT 的行情入口，再按
[MD01 行情使用说明](md01_market_data.md)配置未跟踪的 `.env`。API 和 Migration
就绪后，在 Windows 主机运行：

```powershell
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt run-agent
```

打开 <http://127.0.0.1:5173/market> 查看连接、搜索、自选、实时行情和 K 线。自选股分组
只有开启行情订阅才会驱动期望订阅；页面上的等待状态不等于 MiniQMT 已经实际订阅。
MiniQMT 客户端与行情代理都需要保持运行。本能力只读，交易功能未启用。

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

默认 `RESEARCH_ONLY` 模式只保留六个主入口：**首页、行情、智能选股、策略研究、资讯研究、
设置**。建议依次完成 MiniQMT 行情检查、全市场扫描、单策略快速回测，再按需要查看资讯和
高级研究记录。策略运行、研究信号、扫描运行、历史回放和数据中心仍保留，但不再占用主导航。
独立订单、成交、持仓与风控操作在研究模式下关闭。

### 第一次运行 Scanner

打开“条件扫描”，选择 `volume_anomaly` 或 `limit_up_pullback`、DAY_1 和研究标的后运行；
fixture 已预先生成两次可在“扫描运行”打开的结果。

### 第一次运行 Strategy

打开“策略研究”。通常直接进入“快速回测”；只有需要理解策略参数或排查触发原因时，再进入
“策略模板”“策略运行”和“研究信号”。Strategy 只生成 Signal，不会创建真实订单。

### 第一次运行 Backtest

打开“策略研究 → 快速回测”，选择股票、策略、参数和日期范围。正式页面固定读取已同步到
本地数据库的 MiniQMT 历史日线。回测使用独立账户，并按 T 日收盘 Signal、下一有效交易日
开盘执行。详情应包含指标、权益曲线、订单、成交和完整性检查。

### 第一次运行历史回放

打开“历史回放”，选择与回测相同的本地日线、策略和参数。建议先选 MANUAL：创建后点“单步”
逐日观察 Session、K 线、Signal、风控、订单、成交、账户和 Timeline；再用 X10 验证自动 Worker。
完成后检查最终指标与 Integrity。页面中的历史时间不是实时市场，回放不会连接 MiniQMT 或券商。

### 资讯与 AI

在“资讯中心”手工录入来源后，可从“AI 研究”选择事实运行 Fake 演示。AI 输出仅供研究。
若要启用真实 AI，按 [真实 AI Provider](real_ai_provider.md) 把 Provider、Base URL、Key 和模型
写入本地 `.env`，重新构建/启动 API，再先运行 `provider-status` 和 `test-provider`。不要把 Key
写入 `.env.example`、前端或浏览器请求。
研究模式不开放独立模拟订单流程。如需验证历史策略产生的订单、成交、资金与持仓变化，请在
“快速回测”的详情中查看隔离的模拟事实。

## 4. 状态和常见错误

- `READY`：当前代码、数据和配置满足使用条件。
- `NEEDS_DATA` / `NOT_READY`：前往数据中心补数，或运行 fixture 初始化。
- `NEEDS_CONFIG`：需要启用受支持 Provider；页面不会展示 Secret。
- `DEMO_ONLY`：仅 Fake AI 或明确演示数据，不代表生产可用。
- `DISABLED`：按安全基线关闭，例如 MiniQMT 交易。
- `NOT_IMPLEMENTED`：尚未开发的规划能力。

若显示“无法连接 API”，先运行 `docker compose ps`，确认 API、PostgreSQL、Redis 均为
healthy；再访问 <http://127.0.0.1:8000/health/ready>。若页面仍旧，执行
`docker compose up --build -d` 后刷新。Correlation ID 可用于定位受控错误，但不要粘贴密码、
Token 或连接串。

MiniQMT 是唯一正式行情源，只有本机配置并启动 Windows 行情代理后才可用；断开时不会回退
到免费源或测试数据。它不是真实交易。AI 默认为 Disabled（U01 fixture 可显式使用 Fake）。A01-P 是否可用取决于
本地凭据与兼容服务。

## 5. 第一次使用历史分钟数据

打开 <http://127.0.0.1:5173/market-data-center?tab=minute>，选择股票后查看 1/5/15/30/60
分钟覆盖、质量和 K 线预览。缺少历史数据时，从 MiniQMT 发起 1 分钟补数；5/15/30/60
分钟线由系统按 A 股交易时段聚合。旧分钟页面地址会自动跳转到该页签。
