# StrategySpec 安全策略规则

`StrategySpec` 是用户策略的版本化、可校验结构，不是 Python 源码。它只允许白名单字段、
指标、比较运算和 AND/OR 组合。编译器将规则解释为既有 `Strategy`，策略仍只产生
`Signal`，订单、成交和账本由 BT01 的后续边界处理。

安全限制包括：

- 禁止 `eval`、`exec`、import、SQL、文件、HTTP、环境变量和系统命令；
- 禁止 Broker、MiniQMT 下单和 Order 创建动作；
- 最大文本 1000 字，最大 AST 深度 4，最多 16 个条件，窗口最大 500；
- 未知字段、未知指标、额外 JSON 字段、NaN 和 Infinity 均被拒绝；
- 历史窗口默认排除当前 K 线，避免未来数据。

用户策略保存为定义和不可变版本。每次快速回测另存当时的 Spec 快照，之后修改策略不会
改变历史回测的含义。表结构见迁移 `0023_ux02b_strategy_specs.py`。
