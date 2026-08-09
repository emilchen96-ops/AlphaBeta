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

## 数据计划与双窗口

`DataRequirementPlan` 记录点时股票数、统一市场窗口、逐股补足窗口、所需交易日数量、
字段、参考数据、特征、Provider 方案和预计缺失股票数。CAL01-R 把窗口明确分成两层：

- **市场事件窗口**：所有股票共享同一组真实 A 股开放日，用于“最近 N 个交易日涨停过”
  等事件条件，保证横向可比；
- **个股有效 K 线窗口**：对均线、均量、ATR 等指标按该股票真实可交易 K 线计数，
  已知停牌日跳过并向前补足，但不扩大市场事件窗口。

窗口使用已同步的权威交易日历计算：

```text
所需交易日 = 最大规则窗口 + ALPHADESK_SCREENING_WARMUP_BUFFER_SESSIONS
```

默认预热缓冲为 10 个交易日，逐股向前补足上限默认为 60 个市场交易日。涨停回踩和
首板断板缩量回调额外需要可靠的涨跌停语义；后者固定需要 6 个规则交易日加 10 日预热，
并按共同市场日历核对首板、次日断板和随后三日。底部放倍量只准备区间高低价、均量、
量比和阳线特征，不会重建无关指标。

## 增量补数与幂等

缺口按本地已有 Bar 与所需开放交易日的差集确定，再合并成连续区间。每批最多 50 只，
通过既有 MiniQMT 历史行情队列请求，已有完整窗口的股票不重复下载。一次任务的计划、
准备统计、请求时间和 READY 股票范围持久化在 `scan_runs.execution_stats`；相同幂等键
和相同请求返回原任务。

MiniQMT 返回后 Worker 再次读取 PostgreSQL，而不是信任队列返回值。补数后仍缺少真实
开放日 K 线的股票标为 `DATA_GAP`；只有 MiniQMT 请求明确失败的股票才标为
`PROVIDER_FAILED`。若大量股票集中缺少同一个日期，系统先标记 `CALENDAR_MISMATCH`
并停止对该日期重复补数。其他股票继续执行。高级选项“仅使用当前已有数据运行”会跳过
下载，并按具体原因分类。

## 单股就绪状态

- `READY`：窗口和质量满足当前条件；
- `INSUFFICIENT_HISTORY`：当前已有数据不足且未请求补数；
- `REFERENCE_DATA_MISSING`：缺少必要的复权或参考事实；
- `QUALITY_FAILED`：重复 Bar 或数据质量错误；
- `PROVIDER_FAILED`：MiniQMT 请求明确失败；
- `DATA_GAP`：应有开放日仍缺少 K 线；
- `CALENDAR_MISMATCH`：大量股票集中缺少同一“开放日”，疑似日历错误；
- `CURRENTLY_SUSPENDED`：筛选日当前停牌，有足够历史可审计计算但不输出当日候选；
- `STALE_DATA`：长期无新 K 线且超过允许阈值；
- `NOT_APPLICABLE` / `LISTING_HISTORY_TOO_SHORT`：新股尚未积累规则要求的最小历史；
- `DELISTED`：筛选日已经退市；
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
下载中、新股历史不足、当前停牌、长期无行情、真实开放日缺口、日历异常、不可判定、
Provider 失败、质量失败、已计算、命中、百分比和耗时。
补数阶段另外返回当前运行的总批次、已处理批次、Redis 待处理批次、下载百分比和预计
剩余时间。该下载进度只统计 `scan_run_id` 与当前选股运行一致的 MiniQMT 请求，不混入
其他扫描或维护任务；最后一个批次被 Agent 领取后，在 PostgreSQL 写入和完整性复检完成前
最多显示 99%，避免把“队列已取完”误报成“数据已全部可用”。
重试会创建新的、只包含失败股票的可审计任务，不修改原任务。

## 持久化与迁移

Migration `0026_sc02d_screening_data_preparation` 扩展 `scan_runs.status` 长度和状态约束；
CAL01-R 的 `0027_cal01r_screening_calendar_semantics` 扩展逐股状态约束。数据计划与准备
快照使用现有 JSONB 审计字段，避免为可重建的派生特征新增事实表。

## 安全边界

该链路只访问 Instrument、交易日历、参考数据和 MarketBar，只向 MiniQMT 历史行情
队列发送只读请求。它不读取账户、资金、持仓、委托或成交，不导入交易 SDK，不创建
Signal、RiskDecision、Order 或 Fill，不下单、不撤单，也不修改账本。

## 重试、幂等与审计

同一任务不会因重试而删除或覆盖旧记录。重试只针对真实缺口、明确 Provider 失败、陈旧
数据或修正后的日历异常；关闭日、已知停牌日、上市前和退市后日期永远不进入补数队列。
计划快照会保存具体市场交易日列表、扩展窗口、分类计数和日历异常日期，便于复盘。

## 历史验收记录

2026-07-28 在正式 PostgreSQL、Redis、API、Web 和 Scanner Worker 上分别运行了
“涨停回踩”和“底部放倍量”。两个任务均使用本地 MiniQMT 正式行情事实，未启用 Fixture：

- 涨停回踩：全市场 5,531 只，规划 32 个交易日，识别 5,519 只需要补数、
  12 只不适用，总耗时 6,628ms；
- 底部放倍量：全市场 5,531 只，规划 71 个交易日，识别 5,500 只需要补数、
  31 只不适用，总耗时 8,358ms。

该记录是 CAL01-R 之前的基线。随后发现旧 Fixture 日历把 2026-06-19 误标为开放日，
导致 4,396 只股票同时被误判为 Provider 失败。CAL01-R 已把它修正为端午节休市日，
并增加上述双窗口与分类语义；最终真实环境复验结果应记录在本任务验收报告中。
