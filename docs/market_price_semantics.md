# 市场价格语义

AlphaDesk 以 RAW 未复权日线作为成交和账本的唯一权威价格。D02 引入的 QFQ 是可重建的研究视图，不是另一套成交事实。

| 使用场景 | 价格语义 |
|---|---|
| 技术指标、趋势策略 | RAW 或 QFQ，长期研究推荐 QFQ |
| volume_anomaly | volume 保持原值；价格过滤明确选择 RAW/QFQ |
| limit_up_pullback、涨跌停识别 | 强制 RAW 与 RAW 前收盘 |
| BT01/RT01 策略输入 | RAW 或 QFQ |
| BT01/RT01 SESSION_OPEN 成交 | RAW |
| SESSION_END 估值 | RAW |
| Order、Fill、费用、现金和持仓账本 | RAW |

策略选择 QFQ 时，`StrategyBar` 和 Signal 元数据记录调整模式、RAW 参考价与因子。执行器必须按同一 Instrument 和 Session 重新读取 RAW 开盘价；绝不能把 QFQ 虚拟价格用于真实金额或手续费计算。

数据中心分别显示 RAW、QFQ、Calendar、Suspension、Scanner、Strategy、Backtest 与 Replay Readiness。QFQ 未就绪不会阻止显式选择 RAW 的研究。

当前范围只有 A 股日线。分钟复权、分钟行情、分钟回测、实时交易和 MiniQMT 均不在 D02。
