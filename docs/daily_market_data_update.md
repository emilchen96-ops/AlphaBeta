# D01-C 历史日线每日增量更新

> D02 增强：未显式指定 `target_date` 时，服务优先使用已同步交易日历计算 Asia/Shanghai
> 语义下的最新已完成开放交易日；周末和节假日不会触发无意义补数。已知停牌标的计入
> `suspended_instruments`；日历覆盖不足时沿用兼容日期并在运行元数据返回 WARNING 计数，不会
> 把该回退伪装成已确认交易日。

## 使用边界

`DailyMarketDataUpdateService` 只更新 BaoStock、`DAY_1`、未复权历史 K 线。它是同步的受限操作，不是后台任务，不提供实时 Quote，不写 Redis，不访问 MiniQMT，也不会启动 Scanner、Strategy 或回测。

## 日期与幂等

- 显式 `target_date` 不得晚于上海本地当前日期；为空时优先取交易日历中的最新已完成开放日。
- 已有数据从 `latest_trade_date + 1` 开始；没有数据从 `ALPHADESK_MARKET_DAILY_DEFAULT_START_DATE` 开始，默认 `2023-01-01`。
- 周末、节假日、停牌和 Provider 无数据均可得到 0 新增，不生成虚假 K 线。
- Provider、Universe、稳定排序后的 Instrument ID 和目标日期组成 operation key；重复完成请求返回原 `MarketSyncRun`，唯一键继续保护 K 线幂等。

每只股票在独立短事务写入。默认串行、请求间隔沿用补数配置、临时失败最多重试两次；全局登录失败停止后续请求。`continue_on_error` 决定单只失败后是否继续，运行终态会准确区分全部成功、部分失败和失败。

## 操作

```text
python -m alphadesk_api.cli.market_data update-daily --provider baostock --universe research --dry-run
python -m alphadesk_api.cli.market_data update-daily --provider baostock --universe research
python -m alphadesk_api.cli.market_data update-daily --provider baostock --universe research --target-date 2026-07-18 --max-instruments 30
```

网页使用 `POST /api/v1/market-data/daily-updates`。第一版同步等待结果，按钮在请求期间禁用；服务端始终执行最大标的数限制。统计包含 requested、up-to-date、completed、failed、fetched、inserted、updated、skipped、invalid、retry 和失败代码，错误摘要不保存凭证或堆栈。
