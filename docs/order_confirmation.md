# M05 人工确认

人工确认是订单从 `WAITING_CONFIRMATION` 到 `QUEUED` 的唯一入口。

确认服务先检查 Action 幂等键，再使用 PostgreSQL `SELECT FOR UPDATE` 锁定 Order，锁后重复检查幂等键，并校验 `expected_order_version`、状态、有效期、模拟账户状态和 Instrument 状态。动作 fingerprint 只包含版本化白名单字段。

成功确认在一个 Unit of Work 中原子写入：OrderAction(CONFIRM)、QUEUED Order/Transition、唯一的 OrderCommand(SUBMIT_ORDER/PENDING)、两个 DomainEvent、AuditLog 和 OutboxMessage(PENDING)，然后一次 commit。

任一步或 commit 前失败都会回滚全部事实。自动化测试在 Action、Transition、Command、Event、Audit、Outbox 前及 commit 前注入故障，并确认订单仍为 `WAITING_CONFIRMATION / row_version=2` 且 Session 可继续使用。

相同幂等请求返回既有结果；同键不同输入、陈旧版本、已取消、已过期或已 QUEUED 请求返回稳定错误码。并发确认以及确认/取消竞争由行锁、版本和数据库唯一约束共同收敛到一个合法事实集。
