# ADR 0015：订单状态机与人工确认

- 状态：Accepted
- 日期：2026-07-16

## 决策

M05 手工订单创建后必须进入 `WAITING_CONFIRMATION`，且只能经带幂等键、expected version 和 PostgreSQL 行锁的人工确认进入 `QUEUED`。策略不得直接创建 Order；后续 S01 只能产生 Signal。

QUEUED 仅代表本地数据库命令事实已创建。取消仅允许 CREATED/WAITING_CONFIRMATION；终态不可迁移，`RECONCILIATION_REQUIRED` 不是终态。

## 后果

所有状态变化都有 Transition、Event 与 Audit 证据；并发请求可以确定性收敛。系统不会因页面重复点击或陈旧版本创建重复命令。代价是所有未来执行链路必须尊重该状态机和人工确认边界。
