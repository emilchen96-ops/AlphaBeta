# D03 分钟时间模型

`MarketBar.bar_time` 表示 Bar 开始时间。数据库保存 aware UTC，A股业务展示使用 `Asia/Shanghai`。09:30 表示 09:30:00–09:30:59；Provider 若提供结束时间，Adapter 必须转换并在 metadata 留存原始语义，业务层不猜测。

普通连续竞价 Session：

| Session | 有效1分钟开始时间 |
| --- | --- |
| 上午 | 09:30–11:29 |
| 下午 | 13:00–14:59 |

11:30、午休和 15:00 不是 1 分钟 Bar 的开始时间。正常开放且可交易日的期望数量为：1m 240、5m 48、15m 16、30m 8、60m 4。

`IntradaySessionTemplate` 是纯领域模型。聚合窗口锚定 09:30 或 13:00，不锚定 UTC 整点/Unix Epoch，不跨午休或交易日。开放日与停牌判断复用 D02 `TradingCalendarSession` 和 `InstrumentTradingStatus`；停牌日不期待 Bar，UNKNOWN 只产生警告。
