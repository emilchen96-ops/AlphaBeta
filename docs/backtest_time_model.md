# BT01 时间模型与未来数据边界

所有配置和持久化业务时间均为 aware UTC；交易阶段由 `BacktestClock` 从 A 股交易日生成，不使用系统当前时间决定回测业务事实。

每个交易日严格按以下顺序推进：

1. `SESSION_OPEN`：先按 instrument_id 稳定顺序处理全部标的的前序订单，只暴露当前 open，不使用 high、low、close。
2. `SESSION_CLOSE`：按 instrument_id 稳定顺序向策略逐根提供截至当前的历史，使用完整 T 日 bar 生成并持久化 Signal，再经过 R01 和 M05；订单不能在 T 日 close 成交。
3. `SESSION_END`：使用截至当日已知的最新 close 估值，保存唯一权益点。

因此 T 日 Signal 最早只能影响该标的下一根可用日线的 open。缺失 K 线不会被伪造；持仓标的当日缺 bar 时沿用此前最后一个已知 close，并记录 `STALE_VALUATION`。多标的同日始终先完成全部 OPEN，再完成全部 CLOSE，最后估值。

DAY 订单只在下一根可用 bar 的开盘尝试一次。未成交或部分成交的剩余数量在该执行日通过现有合法状态路径过期；GTC 可保留至后续可用 bar。

输入 K 线、参数、费用和滑点相同，排序、指纹、时钟、成交和指标必须相同。引擎不使用随机滑点或随机成交。
