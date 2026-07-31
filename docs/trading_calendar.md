# A 股交易日历

D02 将 `TradingCalendarSession` 作为独立、可追溯的市场参考事实。CAL01-R 进一步把
交易所已公告的休市安排作为默认正式日历，禁止用“周一到周五”代替 A 股交易日历。
SHSE 与 SZSE 按日期分别保存是否开放、Session 类型、前后开放日、Provider、抓取时间
和更新时间；数据库日期不做 UTC 日偏移。

## 语义

- `NORMAL` 表示开放交易日；`HOLIDAY`、`WEEKEND`、`SPECIAL_CLOSED` 表示已知闭市；`UNKNOWN` 只表示数据源无法确认。
- `previous_open_date`、`next_open_date` 和 `latest_completed_session` 只从已同步日历计算，不用自然日猜测节假日。
- `latest_completed_session` 使用 `Asia/Shanghai`，15:01 之后才把当日视为已完成。
- 日历缺失会返回 `MARKET_CALENDAR_NOT_AVAILABLE` 或 Readiness WARNING，不静默猜测。
- 同一日期在 SHSE/SZSE 都开放时，研究窗口只计一个市场交易日，不重复计数。
- 2026-06-19 是端午节休市日；2026-06-18 的下一开放日和 2026-06-22 的上一开放日
  都必须跨过该日期。

## Provider 与同步

默认 `verified` Provider 使用项目内版本化、经交易所公告核对的 2024—2026 年 A 股
休市表，来源标记为 `VERIFIED_CN_A_CALENDAR`，无需第三方 Token。`fixture` 仅用于
测试和本地演示；Tushare 只有在启用并提供环境变量 Token 后才允许选择，Token 不进入
数据库、API、前端或日志。正式历史行情仍来自 MiniQMT；交易日历和 K 线 Provider 是
两个独立事实来源。

```powershell
python -m alphadesk_api.cli.market_reference sync-calendar --provider verified --dry-run
python -m alphadesk_api.cli.market_reference sync-calendar --provider verified
python -m alphadesk_api.cli.market_reference status
```

HTTP 接口为 `POST /api/v1/market-reference/calendar/sync` 与 `GET /api/v1/market-reference/calendar`。同步幂等，默认有日期与数量上限。

## 来源优先级与异常处理

正式运行优先使用数据库中来源为 `VERIFIED_CN_A_CALENDAR` 的已同步日历。若历史错误日历
把同一非交易日标成开放，并导致大量股票同时缺少该日 K 线，智能选股必须归类为
`CALENDAR_MISMATCH`，不得向 MiniQMT 对该日期反复补数，也不得伪造空 K 线。修复日历后
重跑即可恢复，原研究记录继续保留。

## 业务接线

D01 用日历确定最新已完成交易日；数据质量只检查开放日缺口；BT01/RT01 用开放 Session
序列运行；SC02/CAL01-R 同时使用统一市场事件窗口与逐股有效 K 线窗口。当前仅支持日线，
不包含分钟回测。
