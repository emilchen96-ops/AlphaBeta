# BT01 绩效指标

`BacktestPerformanceService` 是纯计算服务。权威输入为按时间排序的 EquityPoint、Fill，以及 M04 `FillAccountingResult` 按移动平均成本生成的闭合交易摘要；BT01 不另建 FIFO 持仓成本算法。持久化数值使用 Decimal/NUMERIC。

第一版提供：初始/期末权益、总收益、年化收益、最大回撤、年化波动率、Sharpe、交易日数、买卖成交数、换手金额、各项费用、已实现盈亏、胜率、亏损率、Profit Factor、平均盈利/亏损以及平均/最大敞口。

统一约定：

- 一年按 252 个交易日，默认无风险利率为 0。
- 日收益由连续 EquityPoint 计算。
- 收益波动为零时 Sharpe 返回 null。
- 没有亏损闭合交易时 Profit Factor 返回 null，并附 warning，避免持久化 Infinity。
- 百分比和金额通过 Decimal 或稳定字符串传输，不把二进制 float 作为权威持久化值。
- 结果可由事实重新计算；Integrity 服务会比较重算结果与持久化指标。

这些统计只描述历史模拟结果，不是收益预测或投资建议。
