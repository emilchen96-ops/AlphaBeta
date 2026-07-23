# SC01-R MiniQMT 全 A 股日线条件扫描器

SC01-R 将早期的“小股票池同步扫描”升级为 MiniQMT 全市场后台任务。用户在
`/scanners` 选择扫描日期、排除条件并确认推荐参数即可运行，不需要研究股票池、
Instrument UUID、`DAY_1`、复权代码或幂等键。

## 边界与数据流

正式链路只有一条：

```text
MiniQMT/XtQuant
  -> Windows 只读行情 Agent
  -> PostgreSQL 标准化 MINIQMT 日线
  -> scanner_worker
  -> 纯领域 Scanner
  -> ScanRun / ScanRunMember / ScanResult
```

- 当前仅支持收盘后或历史交易日的日线扫描，不是盘中、Tick 或分钟扫描。
- 正式数据只读取状态正常、来源为 `MINIQMT`、价格语义为不复权（RAW）的本地日线。
- FastAPI 不加载 XtQuant；缺数请求进入现有 Redis 历史补数队列，由 Windows Agent
  分批处理。
- 扫描结果是研究筛选事实，不创建 Signal、风控决策、订单、成交或持仓，也不调用
  MiniQMT 交易接口。

## 全市场范围和默认排除

`ALL_ACTIVE_A_SHARES` 从 MiniQMT 映射后的活跃 `STOCK` 目录解析沪、深、京普通
A 股；ETF、指数、基金、债券、可转债、期货、港股和非活跃股票不会进入候选范围。

默认排除：

- ST、`*ST`（优先读取正式元数据，名称规则只作兼容）；
- 退市整理和非正常上市股票；
- 扫描日停牌股票；
- 历史日线不足或缺少扫描日日线的股票。

可选排除：上市不足 N 个交易日、北交所、科创板、创业板，以及通过名称或代码搜索
后手动排除的股票。每只股票的纳入、排除、缺数、补数、扫描和命中状态都保存在
`scan_run_members`，不会只保存一个“全 A 股”字符串。

## 两个规则

### 成交量异常筛选（volume_anomaly）

用当前日线之前的 `volume_window` 根 K 线计算历史均量，当前成交量除以历史均量
达到阈值时命中。当前 K 线不会进入自身均量。

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| 平均成交量计算周期（volume_window） | 20 个交易日 | 不含当前 K 线 |
| 最低成交量倍数（minimum_volume_ratio） | 2 倍 | 当前量 / 历史均量 |
| 最低成交额（minimum_amount） | 不限制 | 元 |
| 最低股价（minimum_price） | 不限制 | 元 |
| 最低当日涨跌幅（minimum_daily_return） | 不限制 | 前端按百分数输入 |
| 最高当日涨跌幅（maximum_daily_return） | 不限制 | 前端按百分数输入 |

### 涨停后回落起涨区（limit_up_pullback）

在回看窗口中寻找达到收益率阈值的近似涨停日，以涨停日前一交易日收盘价作为起涨
基准，再判断当前价格与基准价距离、交易日间隔、是否仍高于基准价和可选量能确认。
该规则固定读取 RAW 日线，避免复权价格扭曲真实涨跌幅。

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| 回溯交易日数（lookback_days） | 20 | 查找近似涨停 K 线 |
| 涨停判定阈值（limit_up_threshold） | 9.5% | 兼容最小价位误差 |
| 基准价容差（baseline_tolerance） | 5% | 当前价距起涨基准价 |
| 涨停后最短间隔（minimum_days_after_limit_up） | 2 个交易日 | 排除刚涨停的股票 |
| 涨停后最长间隔（maximum_days_after_limit_up） | 不限制 | 可选 |
| 当前价格不低于起涨基准价（require_current_above_baseline） | 是 | 布尔值 |
| 当前成交量最低比例（minimum_current_volume_ratio） | 不限制 | 倍数 |

## 旧独立扫描软件对照

开发前检索到 `C:\Users\60576\Documents\扫描系统`。其中“近一月涨停回落”还包含
板块涨停幅度、涨停后峰值和回撤评分；另一条规则实际名为“成交额平台抬升”，依赖
换手率等当前 AlphaDesk 标准日线尚未保存的字段，并不等同于已封板的
`volume_anomaly`。

SC01-R 因此没有悄悄改变两个既有 Scanner 的核心含义：本阶段复现了旧工具的全 A
范围、默认排除、参数化、单股失败隔离、进度和可读结果；规则计算以 AlphaDesk
现有已测试领域实现为基线。旧工具的换手率平台规则和更完整的板块涨停制度属于后续
独立规则版本，不能在同一 scanner key 下无迁移地替换。

## 数据准备和后台状态

扫描器根据参数计算最低日线数量。缺失股票按每批最多 50 只写入 MiniQMT 历史补数
队列；等待窗口结束后重新检查 PostgreSQL。补数后仍不足的股票记录原因并跳过，
不会使整批失败。计算按可配置批次推进，默认每批 250 只。

状态流：

```text
等待中 -> 解析股票范围 -> 检查历史数据 -> 补齐历史数据
       -> 正在扫描 -> 已完成 / 部分完成 / 已失败 / 已取消
```

Worker 重启后会继续领取等待、数据准备或运行中的持久化任务。结果、成员状态和最终
运行统计在同一数据库事务中封板。

## 数据库迁移

Migration `0021_sc01r`：

- 扩展 `scan_runs` 的状态、排除快照、来源、进度和数据准备统计；
- 新增 `scan_run_members`，保存每次扫描的实际股票范围和逐股原因；
- 保留 `scan_results` 的运行内股票唯一、排名唯一约束；
- 旧的显式 Instrument 扫描接口继续兼容。

## API

```text
GET  /api/v1/scanners/catalog
GET  /api/v1/scanners/session-default
POST /api/v1/scan-runs
GET  /api/v1/scan-runs
GET  /api/v1/scan-runs/{run_id}
GET  /api/v1/scan-runs/{run_id}/data-preparation
GET  /api/v1/scan-runs/{run_id}/members
GET  /api/v1/scan-runs/{run_id}/results
GET  /api/v1/scan-runs/{run_id}/results/{result_id}
POST /api/v1/scan-runs/{run_id}/cancel
GET  /api/v1/scan-runs/{run_id}/integrity
```

结果列表支持分页以及股票编号、代码或名称筛选。全市场运行响应不返回数千个内部
UUID；完整范围从成员接口读取。

## 运行

标准 Docker 环境会启动 `scanner_worker`。本机开发可在 `apps/api` 环境单独运行：

```text
python -m alphadesk_api.workers.scanners
```

Windows MiniQMT 必须已登录并保持只读行情 Agent 运行。目录同步成功不等于历史日线
完整；首次全市场扫描可能花较长时间准备数据。

常用配置：

```text
ALPHADESK_SCANNER_BACKFILL_BATCH_SIZE=50
ALPHADESK_SCANNER_BACKFILL_WAIT_SECONDS=120
ALPHADESK_SCANNER_SCAN_BATCH_SIZE=250
```

## SC01-R 验收记录

2026-07-23 在东莞证券 MiniQMT 模拟行情环境完成一次真实全市场受控验收：

- MiniQMT Agent 已连接，目录同步 7,200 个标的，交易能力保持关闭；
- 全市场任务解析出 5,531 只候选股票，按默认条件排除 207 只；
- 对 5,319 只缺少足够日线的股票创建分批补数请求；
- 在本次等待窗口内 278 只数据达到规则要求并完成扫描，命中 17 只；
- 其余 5,046 只按“历史数据不足”隔离，任务以“部分完成”正常封板，没有拖垮
  FastAPI，也没有产生 Signal、订单、Broker 调用或账户变化；
- 验收过程中发现并修复了全目录成员单次写入超过 asyncpg 32,767 个绑定参数的
  问题，现按每批 1,000 条持久化，并增加回归测试。

离线质量门：Python 单元测试 408 项通过，SC01 数据库集成测试 2 项通过，Alembic
升级/降级/再升级测试通过，前端扫描页测试 6 项通过，TypeScript 类型检查和生产构建
通过。券商非服务时段无法重新登录 MiniQMT，因此交易时段重连后的重复实盘行情验收
作为运行环境复验项保留，不影响已完成的只读扫描代码与数据库封板。

## 已知限制

- 当前补数队列沿用 L2.5-A 的 Redis 请求机制，Agent 没有逐请求完成回执；扫描
  Worker 以数据库重新检查结果作为完成依据。
- 现有涨停规则仍是可配置近似规则，不宣称完整覆盖不同板块、ST、新股和制度变更。
- 旧独立工具的成交额平台/换手率规则尚未迁入，因为标准日线当前没有换手率字段。
