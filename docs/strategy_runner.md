# S01-B 历史策略运行器

## 范围与事实链

S01-B 只提供同步研究运行链路：`PostgreSQL MarketBar -> HistoricalBarProvider -> StrategyRunner -> Strategy -> SignalDraft -> Signal -> StrategyRun`。运行环境固定为 `RESEARCH`，不创建 Order、RiskDecision、Fill、资金或持仓事实，也不提供 API、CLI、页面、调度器或实时运行能力。

## 请求、幂等与时间边界

运行请求由策略稳定键及语义版本、周期、UTC 半开区间 `[start_at, end_at)`、去重并稳定排序的标的、经注册表校验及默认值补齐的参数和 `RESEARCH` 环境组成。上述规范化内容采用稳定 JSON 和 SHA-256 生成 `request_fingerprint`；关联 ID 不参与指纹。

- 同一 `idempotency_key` 与相同指纹：返回原 StrategyRun 和原 Signal，不实例化或重新执行策略。
- 同一 key 与不同指纹：返回 `STRATEGY_RUN_IDEMPOTENCY_CONFLICT`。
- `HistoricalBarProvider` 按 `(bar_time, instrument_id, market_bar_id)` 排序。相同标的和时间存在多个来源事实时拒绝运行，避免静默挑选数据。
- 上下文时间只按当前 K 线单调推进，策略无法看到结束边界或未来 K 线。

## 生命周期与事务

运行器校验注册信息、版本、周期和参数后创建独立策略实例，依次调用 `initialize`、逐根 `on_bar`、`finalize`。每个 SignalDraft 必须与当前运行的策略身份、标的和 K 线时间一致，随后映射为带 `strategy_run_id`、连续序号、策略版本、K 线时间、置信度和元数据的持久化 Signal。

正常路径中的 CREATED/RUNNING/COMPLETED StrategyRun、全部 Signal 和计数在一个 Unit of Work 中原子提交。策略或数据质量失败会回滚该事务，再用新的短事务写入 FAILED StrategyRun；错误信息经过控制或净化，不保留部分 Signal，也不遗留 RUNNING。无历史数据不是失败：运行以 0/0 完成，并返回 `NO_MARKET_DATA` 警告。

## 查询与完整性检查

查询服务提供 StrategyRun 详情、分页列表、按运行分页查询 Signal，以及只读完整性检查。检查比较持久化 Signal 数量与运行计数、连续序号、策略身份及关联 ID，不修复或改写事实。

## 后续边界

S01-B 不等同于完整回测器：没有撮合、资金曲线、手续费、滑点、绩效指标或组合会计。Strategy 仍只能产生 SignalDraft；任何下单能力必须在后续里程碑经风控与订单状态机评审实现。
