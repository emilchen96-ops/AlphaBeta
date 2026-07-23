# MiniQMT 行情订阅模型

## 三类不同事实

1. `WatchlistMember` 是用户长期关注的股票，不等于 MiniQMT 已订阅。
2. `DesiredSubscription` 是系统根据当前业务来源计算出的期望订阅。
3. `ActiveSubscription` 是 Windows 行情代理实际向 MiniQMT 订阅成功并上报的运行状态。

只有打开“盘中监控”的自选股分组才会驱动期望订阅；所有历史自选股不会被无条件订阅。

## 订阅来源与计划

第一版来源为：

- `WATCHLIST`：启用盘中监控的自选股分组；
- `SCANNER`：最近一次完成的 Scanner 结果；
- `BENCHMARK`：配置的系统基准标的；
- `TEMPORARY`：当前打开的行情详情股票，15 分钟 Redis TTL。

`MarketSubscriptionPlanService` 合并来源、按 `instrument_id` 去重、稳定排序并应用数量上限。
超限股票进入 `rejected_instruments`，原因是 `SUBSCRIPTION_LIMIT_EXCEEDED`，不会静默丢弃。
计划内容生成稳定版本；相同输入重复计算得到相同结果。

## 期望与实际的差异同步

`MarketSubscriptionSet` 和 `MarketSubscriptionItem` 保存每版期望集合及来源。
`MarketActiveSubscription` 保存代理上报的实际状态。两者差集产生：

- `instruments_to_subscribe`；
- `instruments_to_unsubscribe`。

`MarketSubscriptionSyncRun` 记录尝试数、成功数、失败数、开始/结束时间和 Correlation ID。
同步使用计划版本和差异指纹保证幂等。部分失败会明确显示；下一轮仍可重试失败差异。
代理重启后不相信旧内存回调，而是根据最新期望计划重建实际订阅并重新上报。

## 自选股操作

创建或编辑自选股分组时可打开“盘中监控”。该开关只改变下一版期望订阅输入，不伪造
MiniQMT 实际订阅状态。用户点击“重新计算订阅”生成计划，点击“同步订阅”创建同步事实；
真正的 subscribe/unsubscribe 由 Windows 行情代理执行。
