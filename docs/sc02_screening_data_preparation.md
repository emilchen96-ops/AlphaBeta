# SC02-D 选股数据自动准备与运行编排

SC02-D 把智能选股入口从“直接读取现有日线”改为完整的后台研究流水线。用户点击
“开始选股”后不需要先进入数据中心手工补数；HTTP 请求只创建任务，Scanner Worker
在后台完成数据规划、缺口补齐、复检、特征预热和筛选。

## 执行链路

```text
ScreeningSpec
  -> ScreeningDataRequirementPlanner
  -> PointInTimeAshareUniverseService
  -> ScreeningDataGapService
  -> MiniQMT 缺失区间队列
  -> 参考数据检查
  -> OHLC / 重复 Bar / 交易日缺口检查
  -> ScreeningFeatureStore
  -> 既有 RuleBasedScreeningEngine
```

阶段状态依次为：

- `PLANNING`：分析规则窗口、字段、参考数据和特征；
- `CHECKING_COVERAGE`：批量检查本地正式日线；
- `BACKFILLING_MARKET_DATA`：按股票和连续交易日区间增量请求 MiniQMT；
- `BACKFILLING_REFERENCE_DATA`：检查交易日历、交易状态、生命周期和复权要求；
- `VERIFYING_DATA`：复检缺口、重复日线和价格合法性；
- `PREPARING_FEATURES`：只预热本次条件需要的特征；
- `SCREENING`：把 READY 股票交给既有 SC02 引擎；
- `COMPLETED`、`PARTIAL_FAILED`、`FAILED`：终态。

## 数据计划

`DataRequirementPlan` 记录点时股票数、最早和最晚日期、所需交易日数量、字段、参考
数据、特征、Provider 方案和预计缺失股票数。窗口使用交易日历计算：

```text
所需交易日 = 最大规则窗口 + ALPHADESK_SCREENING_WARMUP_BUFFER_SESSIONS
```

默认预热缓冲为 10 个交易日。涨停回踩额外需要可靠的涨跌停语义；底部放倍量只准备
区间高低价、均量、量比和阳线特征，不会重建无关指标。

## 增量补数与幂等

缺口按本地已有 Bar 与所需开放交易日的差集确定，再合并成连续区间。每批最多 50 只，
通过既有 MiniQMT 历史行情队列请求，已有完整窗口的股票不重复下载。一次任务的计划、
准备统计、请求时间和 READY 股票范围持久化在 `scan_runs.execution_stats`；相同幂等键
和相同请求返回原任务。

MiniQMT 返回后 Worker 再次读取 PostgreSQL，而不是信任队列返回值。仍有缺口的股票
标为 `PROVIDER_FAILED`，其他股票继续执行。高级选项“仅使用当前已有数据运行”会跳过
下载，并把不完整股票标为 `INSUFFICIENT_HISTORY`。

## 单股就绪状态

- `READY`：窗口和质量满足当前条件；
- `INSUFFICIENT_HISTORY`：当前已有数据不足且未请求补数；
- `REFERENCE_DATA_MISSING`：缺少必要的复权或参考事实；
- `QUALITY_FAILED`：重复 Bar 或数据质量错误；
- `PROVIDER_FAILED`：请求失败或补数后仍不完整；
- `NOT_APPLICABLE`：上市历史不足等点时不适用情况；
- `INDETERMINATE`：规则计算时无法获得可靠涨停价等事实。

只有 READY 股票进入条件计算。“已进入条件计算”不再包含数据不足或 Provider 失败
股票；100% 只表示任务阶段结束，不表示每只股票的数据都完整。

## API 与用户控制

```text
POST /api/v1/research/screenings
GET  /api/v1/research/screenings/{id}/progress
POST /api/v1/research/screenings/{id}/cancel
POST /api/v1/research/screenings/{id}/retry-failed
```

创建请求可传 `use_existing_data_only=true`。进度返回当前阶段、中文动作、总数、READY、
下载中、数据不足、不可判定、Provider 失败、质量失败、已计算、命中、百分比和耗时。
重试会创建新的、只包含失败股票的可审计任务，不修改原任务。

## 持久化与迁移

Migration `0026_sc02d_screening_data_preparation` 扩展 `scan_runs.status` 长度和状态约束，
并扩展 `scan_run_members.status`。数据计划与准备快照使用现有 JSONB 审计字段，避免为
可重建的派生特征新增事实表。

## 安全边界

该链路只访问 Instrument、交易日历、参考数据和 MarketBar，只向 MiniQMT 历史行情
队列发送只读请求。它不读取账户、资金、持仓、委托或成交，不导入交易 SDK，不创建
Signal、RiskDecision、Order 或 Fill，不下单、不撤单，也不修改账本。

## 本地验收记录

2026-07-28 在正式 PostgreSQL、Redis、API、Web 和 Scanner Worker 上分别运行了
“涨停回踩”和“底部放倍量”。两个任务均使用本地 MiniQMT 正式行情事实，未启用 Fixture：

- 涨停回踩：全市场 5,531 只，规划 32 个交易日，识别 5,519 只需要补数、
  12 只不适用，总耗时 6,628ms；
- 底部放倍量：全市场 5,531 只，规划 71 个交易日，识别 5,500 只需要补数、
  31 只不适用，总耗时 8,358ms。

验收时 MiniQMT Agent 状态为 `NOT_CONFIGURED`，因此仅使用当前数据完成了计划、覆盖、
参考数据、质量和终态分类验证，没有把未下载股票或空结果冒充成功。自动增量补数已经由
专项测试覆盖，但全市场真实下载、补数后 READY 与真实入选结果仍须在 MiniQMT 可登录且
Agent 在线时复验。这是外部运行条件限制，不改变只读安全边界。
