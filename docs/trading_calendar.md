# A 股交易日历

D02 将 `TradingCalendarSession` 作为独立、可追溯的市场参考事实。SHSE 与 SZSE 按日期分别保存是否开放、Session 类型、前后开放日、Provider、抓取时间和更新时间；数据库日期不做 UTC 日偏移。

## 语义

- `NORMAL` 表示开放交易日；`HOLIDAY`、`WEEKEND`、`SPECIAL_CLOSED` 表示已知闭市；`UNKNOWN` 只表示数据源无法确认。
- `previous_open_date`、`next_open_date` 和 `latest_completed_session` 只从已同步日历计算，不用自然日猜测节假日。
- `latest_completed_session` 使用 `Asia/Shanghai`，15:01 之后才把当日视为已完成。
- 日历缺失会返回 `MARKET_CALENDAR_NOT_AVAILABLE` 或 Readiness WARNING，不静默猜测。

## Provider 与同步

默认 Fixture Provider 离线、确定性、仅用于测试和本地演示。Tushare 只有在启用并提供环境变量 Token 后才允许选择；Token 不进入数据库、API、前端或日志。BaoStock 仍是 RAW 历史日线主源。

```powershell
python -m alphadesk_api.cli.market_reference sync-calendar --provider fixture --dry-run
python -m alphadesk_api.cli.market_reference sync-calendar --provider fixture
python -m alphadesk_api.cli.market_reference status
```

HTTP 接口为 `POST /api/v1/market-reference/calendar/sync` 与 `GET /api/v1/market-reference/calendar`。同步幂等，默认有日期与数量上限。

## 业务接线

D01 用日历确定最新已完成交易日；数据质量只检查开放日缺口；BT01/RT01 用开放 Session 序列运行。当前仅支持日线，不包含分钟行情或分钟回测。
