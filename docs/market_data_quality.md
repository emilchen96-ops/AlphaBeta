# D01-D 历史行情质量与 Readiness

D02 后，缺口只在已知开放交易日内检查，并排除周末、节假日、上市前、退市后和已知停牌日。新增日历缺失、停复牌缺失、复权因子缺失/非法/跳变及生命周期冲突检查；缺少 Provider 事实会明确产生 WARNING，不伪造确定状态。

## 追加式事实

每次检查创建 `MarketDataQualityRun`，问题以 `MarketDataQualityIssue` 追加保存，不提供编辑、删除、补零或自动修复接口。Migration `0014_d01` 建立两张表和 status/time、severity/time、instrument/issue、run、universe/time 索引。

质量规则包括：业务键重复、严格时间顺序、未来日期、正数且上下界一致的 OHLC、非负 volume/amount、BaoStock Mapping 与交易所一致性、来源混乱、新鲜度、最低 K 线数量、覆盖范围和超过 21 个自然日的启发式间隔。没有权威交易日历时，长间隔只记 INFO，陈旧和数据不足通常记 WARNING；不会把周末或停牌直接判为故障。精确交易日缺口留给 D02。

`MarketDataReadinessService` 独立计算以下能力：两个 Scanner、SMA、放量突破、趋势回调、ATR 通道和日线回测。状态为 `READY/PARTIAL/NOT_READY/UNKNOWN`，WARNING 不会自动使全部能力不可用。BT01-R 已完成，但运行服务仍会独立核对所选来源、未复权、正常质量数据，以及每个请求标的和全局规模上限；Readiness 不会绕过运行前校验。

`MarketDataQualityIntegrityService` 只读核对运行/Issue 总数、severity 统计和 completed_at，不改写历史数据。

```text
python -m alphadesk_api.cli.market_data verify-quality --universe research --timeframe DAY
python -m alphadesk_api.cli.market_data show-readiness --universe research
python -m alphadesk_api.cli.market_data show-quality-run --run-id <uuid>
```

API 为 `POST/GET /api/v1/market-data/quality-runs`、`GET /quality-runs/{run_id}`、`GET /readiness`、`GET /coverage` 和 `GET /overview`。详情查询支持 severity、issue_type、instrument 和分页筛选，统一返回 Correlation ID。
