# R01-A 轻量风控核心

> BT01 的 quantity Signal 通过现有 R01 引擎形成持久化 RiskDecision。只有 PASS 才能创建 M05 Order；REJECT/REVIEW 不创建订单，target_weight 不被引擎猜测换算。回测不绕过现金、可卖数量、价格和限额规则；R01 PASS 也不保证 B01 一定成交。

> R01-A/B/C 已完成。纯评估器保持无框架依赖；持久化、订单安全门和查询契约见 [risk_decision_pipeline.md](risk_decision_pipeline.md)，只读页面见 [risk_ui.md](risk_ui.md)。

R01-A 建立纯 Python、确定性、可组合的轻量风控核心。输入是 `RiskRequest`、只读账户快照、只读标的快照与 `RiskLimits`，输出是 `RiskEvaluationResult`。本阶段只计算决策，不写数据库，不创建既有 `RiskDecision` 事实，也不接入 API、网页、订单管道、Redis、Broker 或 MiniQMT。

## 输入与快照

`RiskRequest` 不是 Order。它描述人工订单、策略 Signal 或系统来源的待评估意图，包含账户、标的、方向、订单类型、Decimal 数量、可选价格与 UTC 时间。LIMIT 必须有 `limit_price`，MARKET 不得携带限价；float、NaN、Infinity 和 naive datetime 均被拒绝。

`RiskAccountSnapshot` 汇总账户类型和状态、可用/总现金、持仓市值、总权益、不可变持仓列表、近期订单时间、未结订单数与账户级 Kill Switch。`RiskInstrumentSnapshot` 保存标的身份、有效状态、整手、最小价位及可选参考价。快照只包含值，不暴露 Repository、Session 或任何账本写入口。

`reference_price` 只用于风险估算，不保证可成交，也不得由历史收盘价伪装成实时价格。LIMIT 使用用户限价估算；MARKET 优先使用请求参考价，然后使用标的快照参考价。缺少 MARKET 参考价且配置要求参考价时拒绝，否则进入人工复核。

## 限制与规则契约

`RiskLimits` 是不可变配置，支持单笔金额、单标的权重、总暴露、时间窗口订单频率、MARKET 开关、MARKET 参考价要求和配置级 Kill Switch。领域层不硬编码真实交易阈值；测试和 Demo 必须显式构造限制。

每个 `RiskRule` 具有唯一 `rule_key` 和 `priority`，并独立评估同一组只读输入。`RuleBasedRiskEvaluator` 按 `(priority, rule_key)` 串行稳定执行，拒绝重复键，并返回所有规则结果。它复用既有 `RiskDecisionType`：`ALLOW` 表示规则通过，`REJECT` 表示拒绝，`REQUIRE_CONFIRMATION` 表示人工复核。任一拒绝决定总体拒绝；无拒绝但存在复核则总体复核；其余为允许。规则异常转换成脱敏的 `RISK_RULE_EXECUTION_FAILED` 复核结果，绝不静默放行。

## 第一版核心规则

- 账户必须为 `SIMULATED + ACTIVE`。
- 标的 ID 必须匹配、处于 active，且整手和最小价位合法。
- 账户级或配置级 Kill Switch 任一开启即拒绝。
- 数量必须符合整手；LIMIT 价格必须为正并符合最小价位；MARKET 必须被配置允许。
- Decimal 估算单笔金额；BUY 检查可用现金，SELL 检查可卖持仓且不允许裸卖空。
- 可选检查单笔金额、成交后单标的权重和成交后总暴露；总权益非正时受控拒绝，不执行除零。
- 订单频率只统计 `(requested_at - window, requested_at]`，左边界不计入、请求时间计入；达到上限即拒绝，不访问数据库。

风控金额估算不包含第一版手续费，也不是最终成交金额。未来 B01 模拟 Broker 仍需执行最终费用、撮合、成交数量与成交价格约束；执行器层还必须独立进行第二层风控。

## Pass-through 边界

`PassThroughRiskEvaluator` 仅允许 `test` 和 `development`，明确返回 `RISK_RULES_BYPASSED` 警告；production 构造会失败。策略不能自行选择该评估器，本阶段也没有把它接入任何应用服务。

R01-A 本身不新增 Migration、ORM 或交易事实；上述持久化和订单接线由 R01-B 在应用层完成。

R01-C 不修改规则算法、事务或并发语义，只增加只读查询、服务端限制展示和受控 Signal 评估入口。浏览器不能改写规则结果或限制。
