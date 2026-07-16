# S01 统一策略接口

> S01-C 已提供策略目录、同步历史研究 API 和查询页面。S01-A/B/C 功能开发完成，但 S01 最终审查与封板尚未执行；接口和页面规则见 [strategy_api_and_ui.md](strategy_api_and_ui.md)。

> S01-B 已在 S01-A 纯契约之上增加同步历史运行、StrategyRun/Signal 持久化和运行幂等；事务与查询规则见 [strategy_runner.md](strategy_runner.md)。策略契约本身仍保持纯 Python。

## S01-A 范围

S01-A 建立纯 Python 的 `MarketBar -> Strategy -> SignalDraft` 契约。它不持久化 Signal，
不创建 Order，也不包含 API、CLI、页面、调度、回测、风险控制、Broker 或实时执行。

## 生命周期

每次运行创建独立策略实例，并依次调用 `initialize(context)`、按时间顺序调用
`on_bar(context, bar)`，最后调用 `finalize(context)`。同一版本、参数、上下文和 K 线序列
必须生成相同的 SignalDraft 序列；策略不得读取当前 K 线之后的数据。

## 核心对象

- `StrategyContext`：保存稳定策略键、版本、运行 ID、UTC 当前时间、只读参数、受控运行环境
  和轻量内存状态。只有 `set_state` 可以修改运行状态，不暴露数据库 Session 或交易接口。
- `StrategyBar`：策略只读 K 线视图，价格、成交量和成交额使用 `Decimal`，时间规范为 UTC，
  并校验 OHLC 关系和非负成交量。它不携带下一根 K 线或持久化来源对象。
- `SignalDraft`：尚未持久化的策略输出，复用 `SignalType` 和 `OrderSide`，数量与目标权重互斥；
  参考价格不代表可成交价格。SignalDraft 不是 Order，不能改变资金、持仓或账本。
- `StrategyMetadata`：不可变的稳定策略键、语义版本、展示信息、支持周期和参数 schema 版本。

## 参数与注册表

参数机制支持 integer、decimal、boolean、string 和 enum，严格拒绝 float、未知参数、缺少必填
参数、越界值和非法枚举。默认值经相同规则校验，结果以只读映射返回。

`StrategyRegistry` 显式保存受信任 Factory，不扫描文件系统、不执行用户上传代码，也不保存运行
单例。重复键和未知键返回受控领域错误；每次 `create_instance` 都产生独立实例；元数据按稳定键
排序。`unregister` 仅在显式启用的测试或开发注册表中可用。

## 示例策略

内置 `sma_crossover` 版本 `1.0.0`，默认参数为短窗口 5、长窗口 20、参考数量 100。
短均线向上穿越长均线时输出 `ENTRY + BUY`，向下穿越时输出 `EXIT + SELL`；数据不足或没有新
交叉时返回空列表。均线只使用已收到的 Decimal 收盘价，不访问数据库或网络。

## 安全边界与后续阶段

策略领域模块不依赖 FastAPI、SQLAlchemy、Redis、Broker、MiniQMT、OrderService 或 Unit of
Work。S01-A 只定义内存契约；S01-B 的应用与基础设施层已处理历史运行、Signal 持久化与只读
查询入口。Strategy 仍只能生成 SignalDraft，不能绕过风险控制直接创建 Order。
