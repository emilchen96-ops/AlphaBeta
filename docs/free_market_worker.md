# 免费行情 Worker

> Sealed status: the default real-time provider is `disabled`. The Worker reports `DISABLED` and a heartbeat without requesting AKShare or restarting indefinitely. BaoStock historical data remains independently available.

入口为 `python -m alphadesk_api.workers.free_market_data`，Compose 服务名为 `market_worker`。它是独立长进程，不由 FastAPI lifespan 启动；API 重启不会创建第二个抓取循环。

## 每轮流程

1. 检查功能开关；禁用时写入 `DISABLED` 状态和心跳，不访问外部源。
2. 以唯一 owner 获取 `alphadesk:market:v1:worker:leader` Redis 租约；未获取者返回 `SKIPPED_NOT_LEADER`。
3. 从全部自选股和所有账户的非零持仓合并订阅集，并写 Redis 摘要。
4. A 股连续竞价时经 provider guard 调用 AKShare/EastMoney 全市场快照，一次只允许一个请求，最短间隔 5 秒。
5. 对持仓优先的前 20 个重点标的，每至少 300 秒串行补齐近期、已完成的 1 分钟 K 线，并发布 `minute_bar_updated`。
6. 解析、校验并原子更新 quote cache；仅变化数据发布到 `alphadesk:market:v1:events`。
7. 将本轮计数和错误摘要写 `market_realtime_runs`，更新来源状态与 Worker 心跳，释放带 owner 校验并周期续租的租约。

## 限流、重试与熔断

- 最大并发固定为 1；配置验证不允许提高。
- 最短调用间隔 5 秒；最多重试 2 次。
- 重试基线 5 秒、15 秒并加 0–1 秒 jitter。
- 活跃快照轮询默认 30 秒且配置下限为 30 秒；无订阅时不访问上游并退至 120 秒空闲轮询。
- 非交易时段、午间休市和周末停止高频上游请求，退至默认 600 秒检查；法定节假日仍需后续交易日历 Adapter 精确识别。
- 分钟线同步默认间隔 300 秒、最多 20 个标的、回看 120 分钟；逐标的串行并共享同一个 provider guard。
- 连续失败 5 次从 `CLOSED` 进入 `OPEN`；600 秒后进入 `HALF_OPEN`，仅放行一个探测；成功回 `CLOSED`，失败重新 `OPEN`。
- 捕获到日志和数据库的错误只保留异常类型和安全摘要，不写响应原文、环境变量或凭据。

## Redis 键

| 键 | 用途 |
| --- | --- |
| `alphadesk:market:v1:quote:{instrument_id}` | 带 TTL、hash、revision 的最新快照 |
| `alphadesk:market:v1:worker:leader` | 单 leader 租约 |
| `alphadesk:market:v1:worker:heartbeat` | Worker 健康检查 |
| `alphadesk:market:v1:source:status` | 来源、熔断和本轮计数 |
| `alphadesk:market:v1:subscriptions` | 合并订阅摘要 |
| `alphadesk:market:v1:events` | 临时 UI pub/sub，不承载可靠交易消息 |

Redis 丢失后 quote 和状态可重建；`market_realtime_runs` 审计仍在 PostgreSQL。不得把该 Pub/Sub 通道替代 ADR 0003/0004 规定的可靠命令、回执或 Outbox。

## 运维

`docker compose ps` 应显示 Worker healthy；`GET /api/v1/market-data/realtime/status` 同时返回心跳。排查时先看开关、leader、熔断状态和订阅数，再运行 `provider-check`。不要通过缩短 5 秒间隔来规避免费源限制。
