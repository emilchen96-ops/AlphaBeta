# 系统能力状态

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
