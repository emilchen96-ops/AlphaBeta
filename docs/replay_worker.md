# RT01 Replay Worker

`replay_worker` 是 compose 中独立于 API 和 market_worker 的进程。它定期写 Redis 心跳，扫描
RUNNING 且非 MANUAL 的回放，利用 PostgreSQL 条件 lease 保证一个 Run 同时只有一个推进者。
Redis 仅用于 worker 在线状态和已提交事件的低延迟通知；ReplayRun、控制动作、事件和交易事实
均以 PostgreSQL 为准。

健康检查读取 `alphadesk:worker:replay:heartbeat`。系统能力接口同时报告历史日线、配置和
worker 状态；Worker 离线时 MANUAL 单步仍可通过 API 使用，但自动播放不可用。

```text
docker compose up -d replay_worker
docker compose ps
docker compose logs --tail 100 replay_worker
```

进程每次只完成一个原子 Session 后更新游标、计数和 lease。数据库提交成功后才发布 Redis 通知；
通知失败不会回滚权威事实，WebSocket 也会从数据库按 sequence 补发。
