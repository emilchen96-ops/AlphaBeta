# B01-A 模拟 Broker 领域核心

> BT01 在下一根可用日线的 SESSION_OPEN 构造快照：open/last/bid/ask 均为 bar.open，不使用当日 high/low/close 决定成交。最大可成交量受 bar.volume、participation rate 和 lot size 限制。执行继续使用 B01 的费用、滑点、Attempt、Fill 和状态机；DAY 剩余量在该执行日合法过期。

> B01-C 已通过本地 API、CLI 和网页复用本契约，操作说明见
> [模拟执行 API、CLI 与网页](simulated_broker_ui.md)。所有入口仍只支持本地模拟账户。

> B01-B 已在独立应用服务中把本契约接入持久化 Fill、M05 状态机与 M04 原子账本；详见
> [模拟执行事实管道](simulated_execution_pipeline.md)。本文件仍只定义 B01-A 纯计算边界。

> B01-A 只提供纯 Python、确定性的模拟执行计算。它不读取或写入数据库，不创建持久化
> `Fill`，不修改订单、资金、持仓或账本，也不调用 Redis、MiniQMT 或任何外部 Broker。

## 契约与边界

`alphadesk_domain.broker` 定义 `BrokerAdapter` 协议。当前唯一实现
`SimulatedBrokerAdapter` 的元数据键为 `simulated`，执行模式为 `SIMULATED`。调用方必须显式
传入以下三个不可变对象：

- `BrokerOrderRequest`：复用既有 `OrderSide`、`OrderType` 和 `TimeInForce`，携带命令、订单、
  账户、标的、数量、价格、有效期及链路标识；
- `ExecutionMarketSnapshot`：调用时刻的显式市场快照；模拟 Broker 不自行查询行情；
- `BrokerAccountSnapshot`：执行约束所需的现金、总持仓和当前可卖数量。

数值只接受有限的 `Decimal`，时间只接受 aware datetime 并规范为 UTC。所有输入与输出均为
冻结 dataclass。非模拟账户由 Adapter 以 `BROKER_ACCOUNT_NOT_SUPPORTED` 拒绝；账户快照本身
仍保留账户类型，以便形成受控拒绝结果。

## 行情与执行价格

市场快照支持 `TRADING`、`SUSPENDED`、`CLOSED` 和 `UNKNOWN`，并校验 OHLC、非负可用量、
正价格及涨跌停关系。历史收盘价不得冒充实时行情；调用方必须说明来源和过期状态，
`is_stale=true` 会被拒绝。

`ExecutionPriceResolver` 使用固定优先级：

- MARKET BUY：`ask_price -> last_price -> close`；
- MARKET SELL：`bid_price -> last_price -> close`；
- LIMIT BUY：上述买入参考价不高于限价才可成交；
- LIMIT SELL：上述卖出参考价不低于限价才可成交。

无可用参考价返回 `BROKER_MARKET_PRICE_UNAVAILABLE`；限价未达到返回 `NO_FILL`。执行不会读取
下一根 K 线，也不会使用 high/low 推断不存在的盘中成交顺序。`FillDraft` 同时保存参考价格与
来源，便于后续审计。

## 滑点

滑点协议为 `SlippageModel`：

- `NoSlippageModel` 原样返回参考价；
- `FixedBasisPointsSlippageModel` 对 BUY 向上、SELL 向下调整固定基点，可设置绝对最大偏移。

所有计算只使用 `Decimal`，无随机数；相同输入产生相同价格。滑点不会跨越显式涨跌停。
LIMIT 订单的最终价格还会受自身限价约束，不能因滑点突破买入上限或卖出下限。

## 费用

`AshareSimpleFeeModel` 是 Demo/测试用的简化 A 股费用模型，不代表用户真实券商费率：

- BUY：佣金、过户费，不收印花税；
- SELL：佣金、印花税、过户费；
- 佣金取按费率计算值与最低佣金的较大值；
- 默认货币精度为 `0.01` 元，使用 `ROUND_HALF_UP`。

费率、最低佣金和精度均在构造时校验，模型不读取数据库或外部配置。

## 成交、部分成交与 T+1

当 `available_volume` 为空时，本次调用可全部成交；有值时最多成交
`min(requested_quantity, available_volume)`；零可用量返回 `NO_FILL`。每次 `submit` 最多
生成一个 `FillDraft`，`sequence_number=1`。FOK 在可用量不足时不产生部分成交，其余已支持
TIF 可按当前快照产生部分成交；本阶段不模拟盘口队列、拆单或随机成交概率。

BUY 在生成草稿前重新检查现金是否覆盖成交金额和全部费用。SELL 只允许成交数量不超过
`sellable_quantity`，不允许卖空。`position_quantity` 是总持仓，`sellable_quantity` 是当前
可卖持仓；Broker 不自行计算 T+1 冻结或解冻。

`FillDraft` 不是数据库 `Fill`。它校验：

- `gross_amount = quantity * price`；
- `total_fee` 等于各费用之和；
- BUY 的 `net_cash_effect` 为负，SELL 为正；
- 成交标识和执行引用由执行指纹确定，不使用随机结果。

B01-B 通过受控应用服务把执行结果接入 M05 状态机与 M04 `FillAccountingService`；B01-A 本身仍不
执行这些动作。

## 结果与确定性

`BrokerExecutionResult` 支持 `FILLED`、`PARTIALLY_FILLED`、`REJECTED`、`EXPIRED` 和
`NO_FILL`，并强制数量守恒、Fill 数量合计、平均成交价和无成交结果约束。拒绝顺序固定为：

1. 请求能力；
2. 账户类型、标识和状态；
3. 标的与市场状态；
4. 过期时间；
5. 参考价与 LIMIT 条件；
6. 滑点与涨跌停；
7. 可成交量；
8. 费用；
9. BUY 现金或 SELL 可卖持仓。

`execution_fingerprint` 使用稳定排序 canonical JSON、Decimal 字符串、UTC 时间和 SHA-256，
覆盖 Broker、命令、订单、账户、标的、方向、类型、数量、限价、市场快照及费用/滑点版本。
本阶段只计算指纹，不持久化幂等执行记录。

## 安全结论

R01 PASS 只允许创建 M05 订单事实，不保证 Broker 最终成交。B01-A 仍没有 Windows 执行器、
Broker 外部连接、API、CLI、网页、数据库写入或实盘能力。
