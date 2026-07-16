# 行情 WebSocket 契约

地址：`/ws/v1/market-data`。协议 `schema_version=1`，只读且不接受任何订单、成交、账户或 Broker 指令。Origin 必须为空或在 `ALPHADESK_CORS_ORIGINS` 中。

## 客户端消息

```json
{"schema_version":1,"type":"hello","instrument_ids":["uuid"]}
{"schema_version":1,"type":"subscribe","instrument_ids":["uuid"]}
{"schema_version":1,"type":"unsubscribe","instrument_ids":["uuid"]}
{"schema_version":1,"type":"ping"}
```

单连接订阅上限默认 200，消息上限沿用 `ALPHADESK_MAX_WEBSOCKET_MESSAGE_BYTES`。非法 UUID、未知类型、超限消息返回 `error`，不会触发外部数据请求。

## 服务端消息

| type | 含义 |
| --- | --- |
| `connected` | 连接 ID、服务时间和使用限制 |
| `subscription_ack` | 服务端当前订阅全集 |
| `quote_snapshot` | 订阅时从 Redis 读取的初始快照 |
| `quote_update` | revision 单调增加的变化快照 |
| `minute_bar_updated` | 近期分钟线完成写库后的通知 |
| `source_status` | 来源或熔断状态变化 |
| `heartbeat` | 服务端保活 |
| `pong` | 对客户端 ping 的响应 |
| `error` | 受控协议错误 |

API 每个进程只创建一个 Redis Pub/Sub listener，然后按 instrument ID 分发到连接。每个连接使用有界队列；队列满时丢弃最旧的展示消息并在下一事件带 `dropped_messages`，不会无限积压。前端 `MarketDataWebSocketClient` 是进程级单例，合并页面订阅、指数退避重连，并丢弃 revision 未增加的消息。

该通道是可丢失的 UI 更新链路。断线后客户端必须重新 `hello`，服务端从 Redis 发 `quote_snapshot` 恢复；任何需要可靠投递的未来交易消息不得使用此通道。
