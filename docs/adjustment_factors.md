# 复权因子与 QFQ

D02 将 `AdjustmentFactor` 与 RAW `MarketBar` 分开保存。唯一业务键是 Instrument、交易日期、来源和因子约定；因子必须是有限、严格大于零的 `Decimal`。

## 因子约定

第一版明确支持 `NONE` 与 `TUSHARE_CUMULATIVE`。Provider 必须声明约定，系统不会假定不同来源的因子可互换。Fixture 为开放交易日生成确定性的基线因子；没有 Tushare Token 时不会伪造真实 Provider 成功。

## QFQ 计算

给定原始价格 `P(t)`、当日累计因子 `F(t)` 和基准日因子 `F(ref)`：

`QFQ(t) = P(t) × F(t) / F(ref)`

默认基准是查询区间末端，也可显式指定。计算使用 Decimal；OHLC 与 VWAP 调整，volume 和 amount 保留 RAW 含义。结果携带 mode、factor、reference factor 和 raw bar id，绝不覆盖 `MarketBar`。

`GET /api/v1/market-data/bars?adjustment_mode=RAW|QFQ` 提供统一查询。缺失因子返回 `MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE`；HFQ 当前返回不支持，不做伪造。

## 使用边界

QFQ 仅用于技术指标、趋势策略和长期研究图。Signal 会记录参考价格模式；Order、模拟成交、Fill、费用、现金和持仓账本始终使用 RAW。
