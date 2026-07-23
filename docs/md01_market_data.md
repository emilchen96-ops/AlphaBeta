# MD01 MiniQMT 行情使用说明

## 当前边界

AlphaDesk 的唯一正式行情源是 MiniQMT。普通页面不会展示或自动回退到 BaoStock、AKShare、
东方财富、本地文件、演示数据或测试数据。MiniQMT 暂时不可用时，页面显示不可用原因和最后
更新时间，历史数据缺失时显示空状态。

本阶段只有行情能力：

- 可以同步 A 股和 ETF 目录；
- 可以订阅自选股、基准标的和当前临时查看标的；
- 可以接收实时快照并通过 WebSocket 更新页面；
- 可以保存 1 分钟 K 线并聚合 5、15、30、60 分钟 K 线；
- 可以从 MiniQMT 补充指定标的的历史日线或历史 1 分钟线；
- Agent 启动或重连后会自动修复当前订阅范围最近的日线和分钟缺口；
- 交易日 15:10 后，Agent 会自动增量刷新当前订阅范围的日线；
- 不读取账户、资金、持仓、委托或成交；
- 不导入 `xtquant.xttrader`，不能下单或撤单。

## 数据流

```text
MiniQMT
  → Windows 只读行情 Agent
  → Redis 最新快照 / WebSocket 实时推送
  → PostgreSQL MiniQMT 日线和分钟 K 线
  → 行情、扫描、策略和回测
```

PostgreSQL 的 `MarketBar` 是历史研究事实。每根正式 K 线必须关联来源代码 `MINIQMT`；
正式查询同时按标的、来源、周期、复权方式、质量和时间范围过滤。Redis 只保存可重建的最新
快照，不代替历史数据库。

## 首次配置

1. 将 `.env.example` 复制为未跟踪的 `.env`。
2. 确认以下本地配置：

```text
ALPHADESK_HISTORICAL_MARKET_PROVIDER=miniqmt
ALPHADESK_AUTHORITATIVE_MARKET_SOURCE=MINIQMT
ALPHADESK_ALLOW_TEST_MARKET_DATA=false
ALPHADESK_MINIQMT_MARKET_DATA_ENABLED=true
ALPHADESK_MINIQMT_DATA_PATH=D:\QTM\DWZQ_QMT\userdata_mini
ALPHADESK_MINIQMT_AGENT_API_URL=http://127.0.0.1:8000
```

3. `ALPHADESK_MINIQMT_AGENT_TOKEN` 应使用本机随机值，并在 API 与 Windows Agent 使用的
   环境中保持一致。不要提交 `.env`。
4. 安装只读 SDK：

```powershell
.\apps\api\.venv\Scripts\python.exe -m pip install -e ".\apps\api[miniqmt]"
```

## 每次开机的启动顺序

1. 启动东莞证券 QMT 模拟版，登录“行情”入口并保持运行。
2. 启动 PostgreSQL、Redis、API 和网页：

```powershell
docker compose up --build -d postgres redis api web
```

3. 在仓库根目录启动 Windows 只读 Agent：

```powershell
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt run-agent
```

4. 打开：

- 行情：<http://127.0.0.1:5173/market>
- 数据中心：<http://127.0.0.1:5173/market-data-center>
- API 文档：<http://127.0.0.1:8000/docs>

关闭时先用 `Ctrl+C` 停止 Agent，再运行：

```powershell
docker compose stop web api redis postgres
```

## 行情页面

- 在“A 股标的目录”输入 `300285`、`300285.SZ` 或中文名称，按回车或点“搜索”。
- 点股票后，页面会建立临时 MiniQMT 订阅；离开或切换股票时释放临时订阅。
- “自选列表”保存关注范围。只有启用实时订阅的自选股、基准标的、最新扫描结果和临时查看
  标的消耗订阅额度，不会一次性订阅全市场。
- 分时、1/5/15/30/60 分钟和日线共用 MiniQMT 数据；日线支持不复权和前复权，分钟线
  固定使用不复权价格。历史数据不足时点“从 MiniQMT
  补充历史行情”。
- K 线按时间升序展示，并显示来源、周期、复权方式和覆盖范围。正式页面不会用测试 K 线
  填补空白。
- 退市或停用股票不会混入普通目录；精确搜索没有在市结果时，会以“已退市或停用”状态
  显示历史目录记录，但不能加入自选或建立实时订阅。

## 数据中心

数据中心是 AlphaDesk 本地研究数据健康中心，不是数据源选择器：

- “数据概况”查看 MiniQMT Agent、目录、日线和分钟线最新状态；
- “日线行情”查看覆盖度、研究可用性并发起受限补数；
- “分钟行情”查看 1/5/15/30/60 分钟覆盖、质量和真实 K 线预览；
- “数据质量”检查缺口、重复、异常价格和时间错位；
- “高级数据管理”查看交易日历、复权因子、停复牌、生命周期、写入记录和质量明细。

历史补数是异步请求。Windows Agent 必须保持运行；完成后刷新页面。单次请求受到标的数量和
日期范围上限保护，不会默认下载全市场多年分钟数据。

## 状态与故障排查

| 页面状态 | 含义与处理 |
| --- | --- |
| 尚未配置 | 检查 `.env` 的 MiniQMT 开关、数据目录和 Agent URL |
| 等待行情代理 | API 已启用，但 Windows Agent 没有运行或心跳已过期 |
| 连接失败 | 确认 MiniQMT 已启动并登录行情；查看 Agent 控制台的中文错误 |
| 页面推送已断开 | 检查 Redis、API 和 WebSocket；页面不会改用其他行情源 |
| 当前标的等待订阅 | 等待 Agent 下一次订阅同步；检查订阅上限和行情权限 |
| 已退市或停用 | 不会实时订阅；只有本地已有历史数据时才能查看历史 K 线 |
| 尚无历史行情 | 在行情页或数据中心发起 MiniQMT 历史补数 |
| 数据延迟 | 核对 MiniQMT 登录状态、市场是否开市以及最后行情时间 |

只读诊断命令：

```powershell
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt market-status
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt list-subscriptions
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt rebuild-subscriptions
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt sync-subscriptions
```

## 已知限制

- Windows Agent 必须与已登录的 MiniQMT 运行在同一台 Windows 电脑上。
- 实时订阅只覆盖研究关注范围，不订阅全部 A 股。
- 大规模历史补数需要分批完成；任务期间不可关闭 MiniQMT 或 Agent。
- 自动缺口修复只处理订阅范围且受单次标的上限保护；全市场多年数据仍需按研究范围分批补数。
- 当前只实现不复权事实和前复权研究视图，不提供后复权。
- MiniQMT 目录同步保留最后一次成功结果；退市证券默认不进入普通搜索。
- MiniQMT 接入仍然是行情接入，不代表券商交易、账户或资金已经接入。
