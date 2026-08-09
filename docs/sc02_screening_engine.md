# SC02-A 全 A 股标准条件目录与规则选股引擎

SC02-A 在 SC01-R 的持久化扫描任务和 MiniQMT 本地日线基础上，引入标准条件目录、
安全的结构化筛选规格、历史点时股票池和统一规则引擎。当前包含涨停回踩、底部放倍量，
并扩展了可审计的“首板断板缩量回调”形态；不执行用户代码或交易指令。

## 处理链路

```text
ConditionCatalog
  -> ScreeningSpec
  -> PointInTimeAshareUniverseService
  -> SC02-D 数据需求规划、缺口补齐与质量复检
  -> PostgreSQL 批量读取已就绪的 MiniQMT MarketBar
  -> ScreeningFeatureStore
  -> RuleBasedScreeningEngine
  -> ScanRun / ScanResult / 中文入选解释
```

API 只创建后台任务，不等待全市场计算完成。PostgreSQL 是任务、进度、规格快照和结果
的权威来源；原始 `MarketBar` 是特征的权威来源。执行器每批隔离单股异常，终态支持
`COMPLETED`、`PARTIAL_FAILED` 和 `FAILED`。

SC02-D 起，后台任务不会直接把本地缺数股票全部计为失败，而是先执行
[选股数据自动准备与运行编排](sc02_screening_data_preparation.md)。原
`RuleBasedScreeningEngine` 的规则语义、排序和解释保持不变。

## ConditionCatalog

每个条件定义包含稳定键、中文名称、说明、分类、参数 Schema、必需字段、最少历史
K 线数、支持周期、复权模式、受控计算器键、解释模板、版本和启用状态。

首版普通条件：

- `N_DAY_HIGH_BREAKOUT`
- `N_DAY_LOW`
- `SMA_RELATION`
- `EMA_RELATION`
- `AVERAGE_VOLUME`
- `VOLUME_RATIO`
- `N_DAY_RETURN`
- `RANGE_POSITION`
- `BULLISH_CANDLE`
- `AMOUNT_THRESHOLD`
- `TRADING_STATUS`

首版标准形态：

- `LIMIT_UP_PULLBACK`
- `FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK`
- `BOTTOM_VOLUME_EXPANSION`

增加条件时主要扩展目录定义、参数 Schema 和受控计算器，不需要增加专用页面。

## ScreeningSpec 安全边界

`ScreeningSpec` 是版本化 JSON 快照，包含名称、来源、点时股票池、筛选日期、周期、
条件、排除项、排序规则、`top_n` 和复权模式。字段采用白名单和严格类型校验，拒绝
未知字段以及 Python、SQL、文件路径、HTTP、函数调用、MiniQMT 交易、Order 和 Fill
等可执行或交易语义。

## 历史点时全 A 股

`ALL_A_SHARE` 覆盖沪市、深市和北交所普通 A 股，不限制为 500 只。历史筛选按
`listed_at <= as_of_date < delisted_at` 判断生命周期；生命周期元数据未知时，仅在
筛选日或之前存在正式历史 K 线的股票才可纳入，避免直接用今天的股票目录回看历史。
数据不足和条件不可判定分别计数，不伪装为未命中。

## 涨停回踩

默认参数：

| 参数 | 默认值 | 含义 |
| --- | ---: | --- |
| `lookback_days` | 20 | 过去交易日窗口 |
| `event_selection` | `LATEST_VALID` | 选择最近且完整的涨停事件 |
| `anchor_price` | `PRE_LIMIT_PREVIOUS_CLOSE` | 涨停前一日收盘价 |
| `maximum_distance_pct` | 3% | 当前价距锚点最大比例 |
| `minimum_price_ratio_to_anchor` | 98% | 当前价最低保护比例 |
| `volume_reference` | `LIMIT_UP_DAY_VOLUME` | 涨停日成交量 |
| `maximum_volume_ratio` | 50% | 当前量相对涨停日量上限 |

涨停识别优先读取实际涨停价或明确市场元数据；回退规则按历史日期和板块制度分别处理
主板、创业板、科创板和北交所，不统一假设 10%。ST 缺少可靠涨停价或明确限制比例时
返回“数据不可判定”，不伪造涨停事件。结果保存涨停日、锚点、当前价、距离、保护价、
两日成交量和比例，并生成中文解释。

## 首板断板缩量回调

`FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK` 使用共同 A 股交易日历，不允许因个股停牌或缺数
而把日期静默前移：D0 为首板收盘涨停，D1 为次日未封住涨停，之后按
`consolidation_days` 检查 3 至 20 个共同交易日。观察期最低价均不得跌破 D0 最低价，
最高价均不得超过 `max(D0.high, D1.high)`；观察期最后一日成交量不得超过
`max(D0.volume, D1.volume)` 的 `maximum_volume_ratio`（默认 50%）。
默认再检查 D0 前一个共同交易日未收盘涨停，以确认“首板”。涨停价不能可靠取得、
形态窗口缺失共同交易日 K 线或参照成交量无效时返回不可判断，不将其伪装成未命中。
结果保存形态起止日期、首板低点、两日参照高点、观察期区间高低、参照成交量和缩量比例。

## 底部放倍量

默认使用此前 60 日（排除当前日）最高价和最低价计算：

```text
区间位置 = (当前收盘价 - 60日最低价) / (60日最高价 - 60日最低价)
```

区间位置不超过 20%，当前成交量超过此前 20 日平均成交量 2 倍且收阳时命中，并按
成交量倍数降序稳定排名。分母为零、历史不足或数据非法均受控返回，不读取筛选日之后
的数据。结果保存区间高低价、当前价、区间位置、平均量、当前量、量比、收阳状态和
排名。

## FeatureStore

本阶段采用进程内、查询级缓存，没有新增因子物化表。缓存支持 60 日高低价、20 日
均量与量比、60 日区间位置、收阳、涨停事件及涨停前收盘价。缓存键包含 Instrument、
`as_of_date`、特征版本和原始数据签名；可随时从 MarketBar 重建，签名不一致时回退
批量现算，禁止读取未来 K 线。

## API 与页面

```text
POST /api/v1/research/screenings
GET  /api/v1/research/screenings
GET  /api/v1/research/screenings/{id}
GET  /api/v1/research/screenings/{id}/progress
GET  /api/v1/research/screenings/{id}/results
GET  /api/v1/screening-conditions
GET  /api/v1/screening-templates
```

`/scanners` 提供标准模板和条件积木、筛选日期、基础市场排除项、启动、进度、运行统计、
结果和入选原因。

## 数据库迁移

Migration `0024_sc02a_condition_catalog` 为 `scan_runs` 增加不可变
`screening_spec` 和 `execution_stats` JSONB 快照，并扩展新终态和成员不可判定状态。
目录和 FeatureStore 未额外建表。

## 真实数据验收

2026-07-23 本地 MiniQMT 正式日线验收：

| 指标 | 涨停回踩 | 底部放倍量 |
| --- | ---: | ---: |
| 点时全 A 股 | 5,531 | 5,531 |
| 数据就绪 | 1,494 | 3 |
| 数据不足 | 4,037 | 5,528 |
| 不可判定 | 0 | 0 |
| 单股失败 | 0 | 0 |
| 命中 | 5 | 0 |
| 数据库查询 | 3 | 3 |
| 读取 K 线 | 89,648 | 89,654 |
| 计算批次 | 23 | 23 |
| 总耗时 | 6,541 ms | 6,046 ms |
| 峰值跟踪内存 | 14,005,288 bytes | 14,006,152 bytes |

两次运行均未读取 2026-07-23 之后的 K 线，且每次固定三次批量查询，不随股票数增长，
确认不存在逐股票 N+1。涨停回踩示例：尖峰集团（600668）在 20 个交易日前涨停，
涨停前收盘价 6.98 元，当前收盘价 7.09 元，距锚点 1.58%，当前成交量为涨停日的
19.14%，且未跌破保护价。

由于本地 5,531 只点时股票中仅 1,494 只具备涨停回踩所需窗口、仅 3 只具备底部放
倍量所需窗口，本次真实数据结论为“部分通过”。这是本地历史数据覆盖缺口，不是用
测试数据补齐后的全市场成功结论。

## 安全边界

筛选只读本地 MiniQMT 行情事实，不创建 Signal、RiskDecision、Order、Fill，不修改
现金、持仓或账本，也不加载或调用 MiniQMT 交易接口。
