# D03 A股历史分钟行情数据中心

D03 为 BT02 和未来分钟历史回放准备离线历史分钟数据，不是实时行情，也不连接 Redis Quote、Windows Agent、MiniQMT 或券商。

数据链路固定为 `Fixture/本地CSV → 规范化 RAW 1分钟 → Session聚合 → MarketBar → 质量/Readiness → API/CLI/页面`。权威事实仍是 PostgreSQL `market_bars`，唯一键沿用 `instrument_id + source_id + timeframe + adjustment_type + bar_time`。重复导入幂等，默认冲突策略 `keep_existing` 不覆盖既有权威事实。

Provider：

- `D03_FIXTURE`：CI/本地演示，确定性、无网络；
- `LOCAL_FILE`：CLI 流式 CSV；
- `EXTERNAL_INTRADAY_DISABLED`：明确禁用的未来端口；
- Parquet：当前未安装 `pyarrow`，明确不支持，不伪装成功。

规范 CSV 列为：

```text
symbol,exchange,timestamp,timeframe,open,high,low,close,volume,amount
```

无时区 `timestamp` 必须通过 `--source-timezone` 显式说明。Decimal 始终从字符串解析，不经过 float。HTTP 不提供文件上传，避免任意路径和大文件进入 API 进程；本地文件使用 CLI、扩展名、根目录、文件大小、行数与批次上限。

常用命令：

```powershell
python -m alphadesk_api.cli.intraday generate-fixture --aggregate 5m,15m,30m,60m
python -m alphadesk_api.cli.intraday import-file --path .\bars.csv --source-timezone Asia/Shanghai --aggregate 5m,15m
python -m alphadesk_api.cli.intraday aggregate --instrument 600000 --start 2026-07-06T09:30:00+08:00 --end 2026-07-11T00:00:00+08:00 --targets 5m,15m,30m,60m
python -m alphadesk_api.cli.intraday coverage
python -m alphadesk_api.cli.intraday readiness
```

服务端默认限制：文件 64MB、批次 1,000、单次查询 5,000 Bar、20 个标的、31 天。大规模全市场多年分钟数据和 PostgreSQL 分区不属于 D03。

统一 `HistoricalBarProvider.stream_bars` 按 `timestamp → instrument_id → bar id` 稳定顺序分批读取，区间为 `[start_at, end_at)`；RAW 与按 D02 日级因子派生的 QFQ 都不会向调用方暴露 ORM 对象。既有整批接口保持兼容，BT01/RT01 日线语义未改变。
