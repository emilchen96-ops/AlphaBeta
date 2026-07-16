# 账户估值

## M04.1A 盘中预览

盘中估值先读取 Redis Quote，再按既定来源优先级回退到 PostgreSQL `DAY_1` 收盘事实。Redis 命中可标为实时来源；PostgreSQL 回退必须明确标为历史回退，不能冒充实时价。结果沿用 `COMPLETE`、`PARTIAL`、`STALE`、`UNAVAILABLE` 四种状态，并携带逐持仓来源、新鲜度和缺价信息。

`GET /api/v1/accounts/{account_id}/live-summary` 是只读临时预览：不得修改现金余额、持仓数量、成本、账本条目或持仓投影，也不得创建 `AccountSnapshot`。免费行情仅供研究，网页必须持续展示这一限制。

## M04 持久化估值

账户估值读取 M03 PostgreSQL 行情事实，默认使用优先级最高的活动行情源、`DAY_1` 和 `NONE` 复权。估值不会生成成交，也不会改变成本或已实现盈亏。

- 持仓市值：`quantity × latest_close`。
- 未实现盈亏：`market_value - cost_basis`。
- 总权益：`cash_total + positions_market_value`。
- 已实现盈亏仅来自卖出成交账本，估值不得重算。

每次估值追加 `account_snapshots`，并更新持仓投影的最新价、市值、未实现盈亏和价格时间：

- `COMPLETE`：所有开放持仓都有正常价格，空仓也属于完整估值。
- `PARTIAL`：部分持仓有价格。总市值、总权益和总未实现盈亏返回 `null`，局部合计仅放在元数据中。
- `STALE`：所有持仓有价格，但至少一个行情质量不是 `NORMAL`；仍给出数值并明确标记陈旧。
- `UNAVAILABLE`：开放持仓均无可用价格；权威汇总返回 `null`。

快照记录行情源、已定价/未定价持仓数、最新价格时间和最多 100 个未定价标的 ID。DEMO 行情继续保留来源标记；网页不得把部分估值显示成完整权益。估值是派生结果，不是成交事实。
