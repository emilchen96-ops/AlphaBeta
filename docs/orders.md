# M05 订单事实管道

> B01-C 只允许 `QUEUED`、`BROKER_ACCEPTED`、`PARTIALLY_FILLED` 订单进入本地模拟执行；入口、结果与只读 Fill 查询见 [simulated_broker_ui.md](simulated_broker_ui.md)。

> B01-B 已在 M05 封板边界之外增加本地模拟执行消费者：只有受控服务可锁定 QUEUED Command、推进
> 既有状态机、创建 Fill，并将 Outbox 明确抑制为 `SUPPRESSED`。M05 的创建、确认和取消语义不变。
> 详见 [模拟执行事实管道](simulated_execution_pipeline.md)。

> R01-B 起，公开 `POST /api/v1/orders` 只能经 `RiskGatedOrderService`。R01-C 已在创建响应和订单详情中展示关联 RiskDecision、评估时间与主要规则摘要，并提供双向跳转。风控未通过时不创建 Order。确认、取消及 Outbox 边界不变。

M05 提供本地、人工确认、可审计的订单事实管道。它只接受 `SIMULATED + ACTIVE` 账户和有效 Instrument；不调用 Broker、执行器或 Redis，不创建 Fill，也不改变现金、持仓或账本。

## 创建契约

`POST /api/v1/orders` 强制 `intent_source=MANUAL`。数量和价格在 JSON 中必须使用十进制字符串，服务端拒绝 float、NaN、Infinity、非整手数量和非最小价位价格。LIMIT 必须有用户限价，估算金额为数量乘用户限价；MARKET 不得带限价且不提供估算金额。历史收盘价不得冒充实时价格。

创建使用稳定排序的 canonical JSON、UTC ISO-8601、Decimal 字符串和 SHA-256 计算 request fingerprint。同一幂等键与相同业务输入返回原订单，不同输入返回 `ORDER_IDEMPOTENCY_CONFLICT`。

一次创建事务写入 Order、`START -> CREATED`、`CREATED -> WAITING_CONFIRMATION`、两个 DomainEvent 和一条 AuditLog。最终 `row_version=2`；创建阶段没有 Action、Command 或 Outbox。

## 查询与操作

- 列表支持账户、标的、状态、方向、订单类型、意图来源、创建时间和分页筛选。
- 详情返回安全的账户/标的、Action、Command 和 Outbox 摘要，不返回内部 headers、凭据或 ORM 对象。
- Timeline 合并 Transition、Action 与 DomainEvent。
- 只有 CREATED/WAITING_CONFIRMATION 可以取消或过期。
- QUEUED 表示本地命令事实已创建，不表示已发送；QUEUED 后不能由 M05 取消。

公开端点：`POST/GET /api/v1/orders`、详情、Timeline、confirm 和 cancel。没有状态 PATCH、Fill 写入或任意状态修改接口。

## 能力限制

当前没有交易级实时行情、身份认证、外部 Broker、Outbox Publisher 或实盘能力。B01-B 仅提供本地
确定性模拟成交，应用仍只能在本地可信网络开发，不得部署公网。
