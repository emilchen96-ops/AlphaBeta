# B01-C 模拟执行 API、CLI 与网页

B01-C 将 B01-B 的原子执行服务暴露为本地开发用 API、CLI 和只读网页。它只处理
`SIMULATED` 账户，不连接真实行情、券商、Windows Agent 或 MiniQMT，也不会产生真实交易。

## 操作入口

订单必须先经过 R01 风控、M05 人工确认并进入 `QUEUED`。订单中心只在
`QUEUED`、`BROKER_ACCEPTED` 或 `PARTIALLY_FILLED` 状态显示“模拟执行”。用户必须显式填写
市场时间、交易状态、Bid/Ask/Last/Close、可成交量、涨跌停价、来源、陈旧标志和幂等键，并完成二次确认。

市场快照是用户输入的审计事实，不会触发外部行情请求。R01 `ALLOW` 只允许创建订单，不保证当前快照一定成交。

## HTTP API

- `POST /api/v1/orders/{order_id}/simulated-executions`：提交显式市场快照；Decimal 必须是 JSON 字符串。
- `GET /api/v1/orders/{order_id}/execution-attempts`：按尝试序号升序查询。
- `GET /api/v1/simulated-executions/{attempt_id}`：查看请求、快照、结果、Fill、状态变化及完整性摘要。
- `GET /api/v1/fills`、`GET /api/v1/fills/{fill_id}`、`GET /api/v1/orders/{order_id}/fills`：只读成交查询。
- `GET /api/v1/orders/{order_id}/simulated-execution-integrity`：只报告差异，不修复数据。

Fill 没有 POST、PATCH 或 DELETE 接口。错误响应沿用统一 Correlation ID，不返回 SQL、连接串、内部路径或堆栈。

## 执行结果

- `FILLED`：全部成交并记账。
- `PARTIALLY_FILLED`：只对实际 Fill 记账，剩余数量可用新的快照和幂等键继续执行。
- `NO_FILL`：保存 Attempt，不创建 Fill，不改变现金和持仓。
- `REJECTED`：保存受控拒绝事实，不创建 Fill。
- `EXPIRED`：订单按状态机进入过期状态。

同一幂等键和相同指纹返回原 Attempt；不同指纹返回冲突。所有成交继续复用 M04
`FillAccountingService`，BUY 费用进入持仓成本，SELL 费用从收入扣减，印花税只在 SELL 侧产生。执行成功后刷新订单、Attempt、Fill、现金、持仓、快照和核对结果。

## CLI 与 Demo

```text
python -m alphadesk_api.cli.simulated_broker execute --order-id <uuid> --idempotency-key <key> --last-price 10 --bid-price 9.99 --ask-price 10.01 --available-volume 100
python -m alphadesk_api.cli.simulated_broker list-attempts --order-id <uuid>
python -m alphadesk_api.cli.simulated_broker list-fills --order-id <uuid>
python -m alphadesk_api.cli.simulated_broker verify-integrity --order-id <uuid>
python -m alphadesk_api.cli.simulated_broker run-demo
```

CLI 和 Demo 只允许 `development`/`test`。`run-demo` 使用 `DEMO-001` 与 `SSE:600000`，按固定幂等键执行 BUY、SELL、NO_FILL 和部分成交后补齐；重复运行返回既有事实，不重复写 Fill 或账本。运行前必须已有 M04 Demo 账户及 M03 Demo 标的。

## 页面

订单详情展示风控摘要、Timeline、Command/Outbox 状态、ExecutionAttempt、Fill、账本影响和完整性结果。成交记录页支持账户、标的、Order、方向及时间筛选，并只读展示佣金、印花税、过户费、其他费用、总费用和现金影响。

页面不得出现实盘、真实下单、强制成交、手工 Fill、跳过风控或 MiniQMT 执行入口。
