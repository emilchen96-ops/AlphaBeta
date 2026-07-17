# R01-C 风控查询与只读页面

R01-C 完成轻量风控的网页审计闭环。导航中的“风控 / 风控决策”提供分页、结果、来源、账户、标的、时间和订单关联筛选；详情页展示请求摘要、聚合决策、按序规则事实、账户/标的快照摘要、实际限制、预计指标、关联订单和 Correlation ID。

页面把数据库枚举映射为明确文案：`ALLOW` 显示“风控通过”，`REJECT` 显示“风控拒绝”，`REQUIRE_CONFIRMATION` 显示“需要人工复核”。REVIEW 绝不显示为通过。风控通过只表示当前规则允许创建 `WAITING_CONFIRMATION` 订单事实，不代表已成交、已发送或已被 Broker 接受。

## 当前限制

“风控 / 当前限制”读取 `GET /api/v1/risk-limits/active`，只展示服务端 `ConfiguredRiskLimitsProvider` 的实际生效值。页面没有写入按钮，API 也没有 POST、PUT、PATCH 或 DELETE 配置端点。系统尚无身份认证，浏览器不得修改阈值；修改必须通过本地服务端配置并重新加载服务。Kill Switch 开启时只显示醒目警告，不提供关闭操作。

## 订单和 Signal 边界

订单创建结果展示 RiskDecision。PASS 展示 Decision ID、Order ID 和 `WAITING_CONFIRMATION`；REJECT/REVIEW 展示原因与 Decision 链接，不显示虚假 Order ID，也不自动重试。订单详情与风控详情可以相互跳转。

Signal 页面允许用户选择模拟账户并发起独立风险评估。服务端从 Signal 读取标的和方向，只创建 RiskDecision；仅有 target weight 且没有可用数量时记录 REVIEW。该操作不创建 Order、Fill、现金或持仓变化，不写账本，不发布 Redis，也不调用 Broker、执行器或 MiniQMT。

## 当前能力限制

R01 是后端第一层轻量风控，不是实盘级完整风控。它不替代未来执行器的最终风控、实时行情时效校验、费用/滑点、Broker 状态、设备授权、命令签名、对账冻结和实盘运行控制。下一阶段是 B01 模拟 Broker。
