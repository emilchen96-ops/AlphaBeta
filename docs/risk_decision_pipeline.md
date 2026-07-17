# R01 风控决策事实管道

> R01-C 已完成查询 API、当前限制只读 API、风控页面、订单关联展示和 Signal 独立评估入口。网页边界见 [risk_ui.md](risk_ui.md)。

R01-B 将 R01-A 的纯领域评估器接入 PostgreSQL，并把 `POST /api/v1/orders` 改为不可绕过的后端安全门。系统仍只支持模拟账户，不连接 Broker、执行器、Redis 订单流或 MiniQMT，也不会创建 Fill 或修改资金、持仓及账本。

## 两条应用链路

人工订单读取 PostgreSQL 中的账户、现金、持仓、账户估值快照、标的和近期订单。`ALLOW` 在同一事务内追加 RiskDecision、RiskRuleEvaluation、事件、审计及 M05 初始订单事实；`REJECT` 和 `REQUIRE_CONFIRMATION` 只保存风控事实，绝不创建伪订单。

Signal 只评估并持久化风控事实，永不创建 Order。仅有 `target_weight` 的 Signal 不推测数量，而是记录 `RISK_SIGNAL_TARGET_UNSUPPORTED` 人工复核事实。

## 权威快照与限制

- PostgreSQL 是唯一权威来源；Redis quote、Broker 数据和历史收盘价均不参与 R01-B 判断。
- 无持仓账户的权益可由权威现金投影确定；有持仓但估值缺失时记录人工复核，不以零填充市值或权益。
- 限制由 `ConfiguredRiskLimitsProvider` 从服务端 `ALPHADESK_RISK_*` 配置读取，客户端不能覆盖。
- 指纹包含业务字段及限制版本标记，不包含 correlation ID；同键同指纹回放原事实，同键不同指纹返回冲突。

## 原子性与并发

风控幂等键使用 PostgreSQL 事务级 advisory lock 串行化竞争。RiskDecision 的订单外键为 `DEFERRABLE INITIALLY DEFERRED`，允许先追加决策，再由既有 M05 服务在提交前创建预分配 ID 的订单。仓储只 flush，Unit of Work 独占 commit/rollback。

故障注入点包括决策后、规则后、事件后、审计后、订单后和提交前。完整性服务只报告规则序号、聚合决策、订单关联及 M05 初始事实异常，不自动修复。

## 查询接口

- `GET /api/v1/risk-decisions`（分页及账户、标的、来源、决策、订单关联、时间筛选）
- `GET /api/v1/risk-decisions/{id}`
- `GET /api/v1/risk-limits/active`（服务端实际限制，只读）
- `POST /api/v1/signals/{id}/risk-assessments`（只创建 RiskDecision）

查询返回决策、逐规则事实、限制及账户/标的快照、warnings 和可空 order ID。订单创建通过时额外返回 `risk_decision_id` 与展示值 `PASS`；数据库继续复用既有枚举值 `ALLOW`。

限制端点不返回环境变量名、文件路径或秘密，且不存在风险配置写接口。Signal 评估由服务端锁定 Signal 的标的与方向，客户端不能借此创建 Order。
