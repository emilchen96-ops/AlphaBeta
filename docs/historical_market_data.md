# D01 A 股历史行情数据

D02 语义增强：数据库中的 `MarketBar` 仍是 BaoStock RAW 未复权事实；统一查询可通过 `adjustment_mode=RAW|QFQ` 生成可追溯研究视图。交易日历、因子、停复牌与生命周期分别持久化，不会反写原始 K 线。详见 [市场价格语义](market_price_semantics.md)。

## 状态与边界

D01-A/B 已完成：BaoStock 证券目录可以同步到既有 `Instrument` / `InstrumentMapping`，研究股票池复用 Watchlist，未复权日线以逐标的短事务写入既有 `MarketBar`，整批结果记录在既有 `MarketSyncRun`。本阶段没有新增 Migration。

BaoStock 是免费、尽力而为、仅供研究的历史数据源，不是交易级实时源。D01 不启动 Worker，不写 Redis Quote，不访问 MiniQMT，不创建 Signal、Order、Fill、账户或账本事实。

## Instrument 同步

`InstrumentUniverseSyncService` 调用 BaoStock `query_stock_basic`，仅保留 Provider `type=1` 且代码前缀符合 A 股普通股票规则的记录：

- `sh.6xxxxx` 映射到 AlphaDesk 既有规范 `SSE`；
- `sz.0xxxxx`、`sz.3xxxxx` 映射到 `SZSE`；
- `bj.4xxxxx`、`bj.8xxxxx` 映射到 `BSE`（Provider 返回时）；
- 指数、基金、债券和未知市场代码不会作为普通股票导入；
- `status` 与 `outDate` 决定 `is_active`；`ipoDate`、`outDate` 和 Provider 状态保存在 Instrument/Mapping metadata；
- A 股默认 `lot_size=100`、`price_tick=0.01`、`currency=CNY`，规则只位于后端适配边界。

Instrument 业务键为 `(exchange, symbol)`，Mapping 唯一键为 `(source_id, instrument_id)` 和 `(source_id, external_symbol)`。导入按 500 条小批量执行 PostgreSQL upsert，重复运行更新既有记录而不生成重复事实。

```text
python -m alphadesk_api.cli.market_data sync-instruments --provider baostock --dry-run --limit 30
python -m alphadesk_api.cli.market_data sync-instruments --provider baostock
```

可用 `--codes-file codes.txt` 只同步明确代码；文件可按行或逗号分隔，最大 1 MB、最多 10000 个代码。

## 研究股票池

第一版复用名为 `D01 Research Universe` 的 Watchlist，不建立第二套 Universe 表。支持：

- `manual`：CLI 明确传入 Instrument ID 或代码文件；
- `research`：D01 管理的持久化研究池；
- `all_active_a_share`：按明确 `--limit` 读取活跃 A 股，仅供受控扩展。

```text
python -m alphadesk_api.cli.market_data create-research-universe --limit 300 --dry-run
python -m alphadesk_api.cli.market_data create-research-universe --limit 300
python -m alphadesk_api.cli.market_data create-research-universe --limit 300 --codes-file codes.txt
```

命令会幂等协调 Watchlist 条目与顺序。默认研究池 300 只，硬上限 500；不会默认把全部市场加入补数任务。

## 历史日线补数

`HistoricalMarketDataBackfillService` 只接受 `DAY` / `DAY_1` 与未复权 `NONE` 数据。Provider 返回的价格、成交量和成交额从字符串直接转换为 `Decimal`，不经过 float。`preclose`、`pctChg` 和 `tradestatus` 放入现有 `MarketBar.quality_flags`，避免为非关键 Provider 字段增加列。

```text
python -m alphadesk_api.cli.market_data backfill --provider baostock --universe research --timeframe DAY --start 2023-01-01
python -m alphadesk_api.cli.market_data backfill --provider baostock --universe manual --codes-file codes.txt --limit 30 --timeframe DAY --start 2026-04-18 --end 2026-07-17 --dry-run
python -m alphadesk_api.cli.market_data list-sync-runs --limit 20
python -m alphadesk_api.cli.market_data show-sync-run --run-id <uuid>
```

安全配置：

- `ALPHADESK_MARKET_BACKFILL_BATCH_SIZE=500`；
- `ALPHADESK_MARKET_BACKFILL_REQUEST_INTERVAL_SECONDS=0.1`；
- `ALPHADESK_MARKET_BACKFILL_MAX_RETRIES=2`；
- `ALPHADESK_MARKET_BACKFILL_MAX_INSTRUMENTS=500`。

BaoStock 使用一个受控会话串行处理标的；单只请求最多重试 2 次并指数退避。抓取发生在数据库事务外，每只股票的全部小批次在自己的短事务内提交，所以后一只失败不会回滚此前成功数据。`continue_on_error=false` 会在首个失败后停止，并在运行 metadata 中记录未处理数量。

K 线唯一键沿用 `(instrument_id, source_id, timeframe, adjustment_type, bar_time)`。请求范围头尾均有本地覆盖时整只跳过；否则重新读取并由 PostgreSQL upsert 区分 inserted、updated、unchanged。停牌日不伪造，缺失交易日不自动补零。

## 校验与同步记录

写入前校验正数 OHLC、OHLC 上下界、非负 volume/amount、有限 Decimal、UTC 时间、单标的时间顺序、重复时间戳和 Provider Mapping 一致性。非法行不写入并增加 rejected；只要存在非法行或单只失败，整批不会标记为 `SUCCEEDED`。

`MarketSyncRun.metadata` 记录 operation、universe、请求/成功/失败/跳过/未处理标的数、unchanged bars、重试数和受控失败代码。`error_summary` 不包含堆栈、连接串或 Provider 原始秘密信息。只读接口为：

- `GET /api/v1/market-data/sync-runs`；
- `GET /api/v1/market-data/sync-runs/{run_id}`。

I01 当前功能矩阵没有授权浏览器触发长耗时外部写操作，因此 D01-A/B 只开放 CLI 写入口，没有 POST 同步/补数 API，也没有伪装成异步任务。

## Scanner 与 Strategy

Scanner 和 Strategy 已通过既有 PostgreSQL HistoricalBarProvider 直接读取这些 `DAY_1` MarketBar，不需要另一套导入或转换。使用前先确认目标 Instrument 在研究池中且请求日期覆盖各规则 lookback。D01 验收只手工运行既有 `volume_anomaly`、`limit_up_pullback` 和至少一个既有 StrategyRun；不会自动生成扫描、Signal 或回测任务。

既有研究读取器会把同一 Instrument、同一时间戳的多来源 K 线视为歧义并拒绝运行。正式研究库应在目标日期范围内为每只股票保留一个权威来源；不要把 M03 `DEMO` K 线与 BaoStock K 线写进同一研究数据集后直接运行策略。D01 不改变这项已封板的数据边界。

MiniQMT 负责未来 Windows 本地券商/行情边界，不是历史研究数据落库的前置条件。BaoStock + PostgreSQL 已能独立支持离线 Scanner、Strategy 和后续 BT01-R；D01 不访问券商账户。

## D01-C/D/E 运营闭环

D01-C/D/E 已完成：每日更新从本地最后一根日线增量读取并以 operation key 幂等；质量运行与问题为追加事实；覆盖率、Readiness、同步历史和质量详情由 API/CLI 与 `/market-data-center` 使用。具体见 [每日增量](daily_market_data_update.md)、[质量与 Readiness](market_data_quality.md) 和 [数据中心页面](market_data_center_ui.md)。D01 历史行情数据中心至此完成，下一阶段是 BT01-R；实时行情、MiniQMT 和自动调度仍不在 D01 范围内。

## 2026-07-19 真实 Provider 验收

验收仅写入隔离 `alphadesk_test`，未覆盖默认开发库：

- Instrument：Provider 返回并幂等写入 5,537 个，active 5,200、inactive 337；研究 Watchlist 300 只；
- 小规模：30 只、2026-04-18 至 2026-07-17，30/30 成功，抓取并新增 1,830 根，0 失败、0 拒绝、0 重试；
- 正式首批：300 只、2023-01-01 至 2026-07-17，300/300 成功，抓取 256,408 根，新增 254,578、更新先前小规模数据 1,830，耗时约 5 分 9 秒；
- 正式重复：新增 0、更新 0；边界容差加固为 14 天后的最终复跑为 300/300 按范围覆盖直接跳过、Provider 未重新抓取 K 线；
- 数据库最终值：300 个有日线标的、256,408 根，最早 2023-01-03、最晚 2026-07-17；重复业务键 0、基础 OHLC/成交量错误 0、少于 250 根的标的 0；
- Scanner：`volume_anomaly` 与 `limit_up_pullback` 各扫描 3 只，均 `COMPLETED`、0 结果；
- Strategy：`sma_crossover` 对 600000 的 2026 年数据处理 129 根，`COMPLETED` 并生成 7 个研究 Signal；未创建订单或成交。

这些数字是一次真实环境快照，不是固定测试断言，也不承诺 BaoStock 后续可用性或数据完整性。
