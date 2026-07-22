# 系统能力状态

D02 在 `/api/v1/system/capabilities` 增加 `trading_calendar`、`adjustment_factors`、`suspension_data`、`instrument_lifecycle` 与 `adjusted_strategy_data`。实现状态、Provider 配置状态、数据状态和 availability 分开报告；Provider 未配置不得显示 READY。

`GET /api/v1/system/capabilities` 是首页功能卡片的权威来源。每个模块分别报告：

- `implementation_status`：代码是否完成；
- `data_status`：本地数据是否满足使用条件；
- `configuration_status`：运行配置是否启用；
- `availability`：面向用户的汇总结论；
- `reason`、`required_actions`：原因和可执行的下一步；
- `last_success_at`、`provider`、`mode`：最近数据时间与当前运行边界。

“代码已实现”不等于“现在可用”。例如历史行情代码完成但数据库为空时显示
`NEEDS_DATA`；实时行情安全关闭时显示 `DISABLED`；MiniQMT 尚未开发时显示
`NOT_IMPLEMENTED`；Fake AI 显示 `DEMO_ONLY`。

A01-P 后，`ai_research.configuration_status` 区分 `DISABLED`、`FAKE`、
`REAL_CONFIGURED`、`REAL_AVAILABLE`、`REAL_UNAVAILABLE`；面向用户的 availability 分别映射为
`NOT_AVAILABLE`、`DEMO_ONLY`、`DEGRADED`、`AVAILABLE`、`DEGRADED`。只有本进程真实连通成功才
显示 `AVAILABLE`，Fake 永远不显示为真实 AI 可用。状态接口不包含 API Key。

RT01 新增 `historical_replay`：代码、D01 日线、配置、`replay_worker` 心跳分别报告，避免把
“代码已实现”误写成“当前自动播放可用”。MANUAL 单步不依赖 Worker；自动 X1/X10/X100 需要
Worker ONLINE。回放计数进入 `data_counts.replay_run_count`。

D03 新增 `intraday_market_data`、`intraday_1m`、`intraday_5m`、`intraday_15m`、
`intraday_30m`、`intraday_60m`、`minute_backtest` 和 `minute_replay`。前六项根据 PostgreSQL
分钟 Bar 计数报告数据状态；后两项实现状态固定 `NOT_IMPLEMENTED`，数据状态单独计算。
分钟历史数据不得映射为 `realtime_market_data=READY`。
