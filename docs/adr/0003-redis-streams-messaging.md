# ADR 0003：Redis Streams 用于可靠命令与回执流

- 状态：Accepted

## 背景

后端与 Windows 执行器需要可恢复的异步命令、回执和消费协调，而 WebSocket 断线不具备可靠指令语义。

## 决策

使用 Redis Streams 与 Consumer Group 实现至少一次投递的命令和回执流，配合 ACK、Pending 恢复、有效期和幂等键。

## 原因

Streams 能提供消费组、未确认消息追踪和恢复能力，适合 MVP 的受控部署。

## 后果

所有消费者必须幂等；需持续监控 Pending、积压和恢复过程。

## 被否决方案

仅用 HTTP/WebSocket 下单；假定消息系统天然恰好一次。
