# 盘中实时估值

> The real-time provider is not configured. Historical close prices may only be labeled `HISTORICAL` or `HISTORICAL_FALLBACK`, never real-time.

`GET /api/v1/accounts/{account_id}/live-summary` 是只读、临时计算接口，不修改 `positions`、`account_snapshots` 或账本，也不会产生交易事件。

## 定价顺序

1. 批量读取持仓对应的 Redis 最新 quote。
2. quote 缺失时，按来源优先级批量读取 PostgreSQL 最新 `DAY_1/NONE` 收盘价，并把来源标成 `:DAY_1_FALLBACK`。
3. 两者都缺失时该持仓为 `MISSING`，金额和未实现盈亏为 `null`。

新鲜度按 `received_at` 计算：默认 60 秒内为 `FRESH`，超过为 `STALE`。上游没有 `quote_time` 时仍保持 `null`；估值可以明确使用该接收快照，但不得把接收时间展示成成交时间。

`market_value = quantity × price`，`unrealized_pnl = market_value - cost_basis`，总权益为基础币种现金加可定价持仓市值。存在缺失定价时总体 `UNAVAILABLE`，否则存在过期或日线回退时为 `STALE`，全部实时且新鲜时为 `COMPLETE`。

持久化估值仍通过 M04 的 `POST /valuation-snapshots` 完成，其事实和审计规则不变。盘中估值不能覆盖账本投影，也不能作为自动下单或风控放行输入。
