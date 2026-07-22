# D03 分钟聚合

权威顺序固定为 `RAW 1m → RAW 5/15/30/60m → 查询时QFQ`。不得先调整 1 分钟价格再聚合并伪装成 RAW。

`IntradayBarAggregator` 对乱序输入稳定排序并按标的、来源和 Session 窗口分组：open 取首根、high/low 取极值、close 取末根、volume 求和；amount 有任一非空时求和，全部为空时保持空。输出 metadata 包含 `source_timeframe=MINUTE_1`、`aggregation_version=D03_SESSION_V1` 和窗口策略。

默认 `STRICT_COMPLETE_WINDOW`：缺任一预期 1 分钟 Bar 就不生成高周期 Bar，并报告 incomplete window。可选 `ALLOW_PARTIAL_WINDOW` 只为未来明确声明的特殊 Session 保留，D03 页面不开放它。

`IntradayAggregationIntegrityService` 只读复算 OHLCVA、时间戳和聚合版本，报告差异而不自动修改事实。聚合写入沿用 MarketBar 唯一键，因此重复执行幂等。
