# S02-B1 批量策略研究实验

S02-B1 将策略参数候选网格按参数定义顺序做确定性笛卡尔积展开，并为每个组合复用
现有 `StrategyRunner` 创建独立 `StrategyRun`。未出现在网格中的参数使用注册表默认值；
Decimal 以字符串进入 canonical JSON 和持久化。同步串行运行最多 50 个组合，超过限制
会在运行前拒绝，不截断、不跳过组合。

`StrategyExperiment` 从 CREATED 进入 RUNNING，最终进入 COMPLETED、PARTIAL_FAILED
或 FAILED。实验创建、每个子运行、只追加关联和最终汇总分别使用短事务；单个组合失败
不会删除已经完成的子运行或 Signal。PARTIAL_FAILED 表示成功和失败组合同时存在。

实验幂等指纹覆盖 schema、策略版本、周期、UTC 时间范围、稳定排序标的、规范参数网格
和 RESEARCH 环境。子运行键由实验指纹、组合序号和参数 hash 确定；数据库唯一约束负责
并发认领，重复相同请求不会重复创建 StrategyRun 或 Signal。

比较摘要只报告 bar 数、Signal/BUY/SELL 数、首末 Signal 时间和触发标的数。Signal
身份为 `(instrument_id, bar_timestamp, signal_type)`，组合间使用 Jaccard 相似度；
两个空集合为 1，单边为空为 0。结果不评价参数优劣，不计算收益、回撤、胜率、Sharpe、
资金曲线或持仓曲线。

HTTP API 同步提供创建、分页、详情、组合运行、比较和重合度查询。本阶段没有队列、
Worker 或并行计算。Signal 不是 Order；实验不会创建 Order、RiskDecision、Fill，
不调用 Broker，也不修改现金、持仓或账本。
