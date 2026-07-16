# M05 Transactional Outbox

M05 只负责在 PostgreSQL 中原子暂存订单命令，不负责发布。

`OrderCommand` 使用 `SUBMIT_ORDER / PENDING`、`sequence_number=1`、`schema_version=1`。白名单 payload 包含 command/order/account/instrument 标识、symbol、exchange、方向、类型、TIF、Decimal 字符串数量/限价、UTC 时间与 correlation ID。canonical JSON 稳定排序后计算 SHA-256 `payload_hash`。

相同 payload 同时写入 topic `order.commands.submit.v1` 的 Outbox；Outbox 初始状态 PENDING、attempts=0、published_at/last_error 为空，并关联 `ORDER_COMMAND_CREATED` 事件。数据库约束保证每个 Order 至多一个 SUBMIT_ORDER，以及 event_id + topic 唯一。

PENDING 只表示“消息尚未发布”。M05 没有 Outbox Publisher、Redis Streams、消费者、target device、签名、Executor 或 Broker。后续阶段必须通过独立 ADR 和验收才能发布；不得把当前 QUEUED/PENDING 解释为已下单或已成交。
