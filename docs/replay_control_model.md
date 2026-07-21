# RT01 回放控制模型

状态机为 `CREATED → READY → RUNNING ↔ PAUSED → COMPLETED/STOPPED/FAILED`。终态不可恢复。
首次单步允许 READY 经 RUNNING 完成一个 Session 后落到 PAUSED；到达末尾则直接 COMPLETED。

控制动作包括 START、PAUSE、RESUME、STEP、SET_SPEED、STOP。每个动作必须携带幂等键，
`(replay_run_id, idempotency_key)` 唯一；同键重复请求返回既有结果。Run 使用 `row_version`
和 `SELECT FOR UPDATE` 串行化状态迁移，Worker 使用条件 lease 取得独占推进权。

速度模式 MANUAL、X1、X10、X100 只映射为 Worker 的 wall-clock 等待间隔。策略、订单、成交、
账本的时间全部来自 ReplayClock 的 Session Open/Close/End，不允许由系统当前时间反推业务事实。

暂停只在 Session 边界生效，因而不会留下半个交易日。STOP 是人工终止事实，不伪装成正常完成。
Worker 崩溃后，过期的外部 lease 会把运行置为 PAUSED 并记录 RECOVERY_REQUIRED；用户检查状态后
显式 RESUME，系统不会静默跳过或重复 Session。
