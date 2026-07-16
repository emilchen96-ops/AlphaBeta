# 免费真实行情

> Sealed status: AKShare/EastMoney real-time validation did not pass. No additional free real-time provider will be added. `RealtimeMarketDataAdapter`, Redis, WebSocket, and UI plumbing remain, but the real-time provider is `disabled`; BaoStock is historical-only. MiniQMT remains a future Windows Agent integration after M06. Historical prices are never real-time quotes; this system has no real-trading capability and must not be publicly deployed.

M04.1A 在保留 `DEMO` 确定性行情的同时，引入两个无需账户密钥的只读数据源。它们统一标记为 `FREE_BEST_EFFORT`、`RESEARCH_ONLY`、`NON_TRADING_GRADE`，不得作为自动下单、风控放行或实盘定价依据。

## 能力矩阵

| 来源 | 能力 | 不支持 |
| --- | --- | --- |
| `AKSHARE_EASTMONEY` | `stock_zh_a_spot_em` A 股全市场快照；`stock_zh_a_hist_min_em` 近期 1 分钟线 | 历史全量分钟线、可靠推送、SLA |
| `BAOSTOCK` | 日线；可选 5/15/30/60 分钟历史线 | 实时快照、1 分钟线 |
| `DEMO` | 固定日线与 1 分钟演示数据 | 真实市场语义 |

适配器只返回字符串数值 DTO；应用层通过 `Decimal` 严格解析，float 不允许穿过边界。AKShare 的 pandas DataFrame 和 BaoStock 的结果游标必须在各自 client wrapper 内立即转为普通记录，不进入领域层。BaoStock 日线请求不得包含仅适用于分时频率的 `time` 字段；分钟历史请求才包含该字段。

## 时间与质量

- 所有持久化和 API 时间统一为带时区 UTC；交易所分钟时间按 `Asia/Shanghai` 解析后转 UTC。
- 上游快照未提供成交时间时，`quote_time` 为 `null`，质量为 `INCOMPLETE` 并带 `MISSING_UPSTREAM_QUOTE_TIME`；不得用接收时间伪造交易时间。
- `received_at` 只表示 AlphaDesk 何时收到数据，可用于缓存新鲜度。
- Redis quote revision 只在稳定业务内容变化时增加；重复快照刷新 `received_at` 和 TTL，但不广播；更旧的 `quote_time` 被拒绝。
- PostgreSQL 保存来源能力和运行审计，不保存每一次实时快照。日线与分钟线仍按 M03 幂等键写 `market_bars`。

## 启用和手工命令

默认 `ALPHADESK_FREE_MARKET_DATA_ENABLED=false`。显式启用后启动独立 Worker：

```text
docker compose up -d --build market_worker
docker compose run --rm api python -m alphadesk_api.cli.market_data provider-check --source AKSHARE_EASTMONEY
docker compose run --rm api python -m alphadesk_api.cli.market_data provider-check --source BAOSTOCK
docker compose run --rm api python -m alphadesk_api.cli.market_data sync-instruments --source AKSHARE_EASTMONEY
docker compose run --rm api python -m alphadesk_api.cli.market_data sync-daily --symbols 600000 --start 2026-07-01T00:00:00+00:00 --end 2026-07-15T00:00:00+00:00
docker compose run --rm api python -m alphadesk_api.cli.market_data sync-recent-minute-bars --symbols 600000 --start 2026-07-15T01:30:00+00:00 --end 2026-07-15T07:00:00+00:00
docker compose run --rm api python -m alphadesk_api.cli.market_data free-market-status
docker compose run --rm api python -m alphadesk_api.cli.market_data free-market-run-once
```

外部网页结构和免费接口随时可能变化。升级 AKShare/BaoStock 时必须先更新锁文件、契约测试和外部显式验收，不能在默认 CI 中访问互联网。

Worker 仅在 A 股上午 09:30–11:30、下午 13:00–15:00（Asia/Shanghai，周末除外）执行活跃快照；休市与午间不高频访问免费源。近期分钟线只取已完成分钟，持仓优先、最多 20 个标的、串行且最短每 300 秒同步一次。

## 2026-07-15 外部验收记录

BaoStock 0.9.3 登录健康检查通过；2025-07-01 至 2025-07-15 的 `600000` 日线真实同步成功，接收并写入 11 条记录。AKShare 1.18.64 的 `stock_zh_a_spot_em` 在当前网络对 EastMoney 完整字段请求连续返回远端主动断开；适配器安全降级为 `MarketDataAdapterError/DEGRADED`，没有生成或缓存伪报价。简化字段的 EastMoney 直连探针可返回 200，但任务固定函数的完整快照仍失败，因此不能据此声明外部实时行情已接通。待上游恢复或经新 ADR 评审替换 provider 后重跑外部验收。
