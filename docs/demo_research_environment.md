# U01 演示研究环境

`initialize-research` 将现有模块编排成可重复验收的闭环，而不是引入新的交易算法。

- `fixture`：创建 `U01_DEMO` 数据源、260 条确定性日线、研究自选列表和 `U01-DEMO`
  模拟账户；日线特意覆盖成交量异常、涨停回落以及 SMA 的 BUY/SELL 信号。
- `existing-data`：优先从 `D01 Research Universe` 选择满足最少 K 线要求的本地标的，
  不访问外部网络，也不会改写 D01 数据。
- 所有命令仅允许 `development` / `test` 环境。
- 重复运行使用固定幂等键，返回已有事实，不重复记账。
- `--dry-run` 只做预检，不打开工作单元、不写数据库。
- `--reset-demo` 重新写回确定性 fixture 并重放固定幂等事实，只触碰 `U01_DEMO` 范围；HTTP
  调用还必须显式传入 `confirm_reset=true`。它不会删除或覆盖用户创建的 D01 数据。

验收命令 `python -m alphadesk_api.cli.demo verify-research --json` 是只读的。

状态含义：`READY` 可直接使用，`PARTIAL` 只有部分链路就绪，`NOT_READY` 缺少必要数据或
基础设施，`DISABLED` 是显式关闭，`NOT_IMPLEMENTED` 表示尚未开发。
