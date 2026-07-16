# S02-A 技术指标与基础策略库

## 范围与接口

S02-A 在纯 Python 领域层提供可复用的增量指标。所有数值输入和计算均使用
`Decimal`，不接受 float，不依赖 Pandas、NumPy、数据库或全局缓存。指标统一提供
`update(...)`、只读 `value`、只读 `is_ready` 和 `reset()`；窗口未填满时 `value` 为
`None`。

指标包括 `SimpleMovingAverage`、`ExponentialMovingAverage`、`RollingHighest`、
`RollingLowest`、`AverageTrueRange` 和 `RollingAverageVolume`。EMA 使用前 `window`
个输入的算术平均作为固定初值，之后按 `alpha = 2 / (window + 1)` 递推。ATR 首个
True Range 使用 `high - low`，此后同时考虑相对前收盘价的跳空；前 `window` 个
True Range 的平均值作为初值，之后采用 Wilder 递推。

RollingHighest/Lowest 本身只反映已经 update 的值。策略在判断突破前读取指标值，
再写入当前 bar，即可明确排除当前 bar；先 update 再读取则包含当前 bar。

## 内置策略

### volume_breakout

参数为 `breakout_window=20`、`volume_window=20`、`volume_multiplier=1.5`、
`exit_window=10`、`quantity=100`。FLAT 时，当前收盘价严格高于此前突破窗口最高价，
且当前成交量不低于此前平均量乘以倍数时产生 BUY；LONG 时，当前收盘价严格低于
此前退出窗口最低价时产生 SELL。价格高低点和平均量都不包含当前 bar。

### trend_pullback

参数为 `fast_ema=10`、`slow_ema=30`、`pullback_window=5`、
`pullback_tolerance=0`、`quantity=100`。趋势定义为 fast EMA 严格高于 slow EMA。
“附近”被确定性定义为 `close <= fast_ema * (1 + pullback_tolerance)`；观察到该回调
后，价格在最多 `pullback_window` 根 bar 内重新严格站上 fast EMA，且状态为 FLAT，
则产生 BUY。LONG 状态下 fast EMA 严格低于 slow EMA 时产生 SELL。

### atr_channel

参数为 `ema_window=20`、`atr_window=14`、`entry_atr_multiplier=1.0`、
`exit_atr_multiplier=1.0`、`quantity=100`。每根当前 bar 先更新 EMA 和 ATR，再以
`EMA + entry_multiplier * ATR` 和 `EMA - exit_multiplier * ATR` 形成当根通道。
收盘价由不高于上轨变为高于上轨且状态为 FLAT 时产生 BUY；LONG 时收盘价低于下轨
产生 SELL。持续处于上轨外不会重复 BUY。

## 状态、确定性与安全边界

三套策略均经 `StrategyRegistry` 显式注册。每次 `create_instance` 产生独立实例，运行
状态通过 `StrategyContext` 按标的隔离，仅按严格递增时间消费 `StrategyBar`。策略只
返回 `SignalDraft`，其 `reference_price` 只是当前收盘参考价。指标和策略均不读取未来
bar，也不创建 Order、Fill，不访问仓储、FastAPI、SQLAlchemy、Redis、Broker 或
MiniQMT，不修改现金、持仓或账本。S02-A 不提供撮合、收益、回撤或完整回测能力。
