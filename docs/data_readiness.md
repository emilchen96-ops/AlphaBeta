# I01 数据与配置就绪度

> D01-A/B 追加验收（2026-07-19）：在显式联网的隔离 `alphadesk_test` 库同步 BaoStock 5,537 个 A 股 Instrument（5,200 active），创建 300 只研究池，并写入 256,408 根 `DAY_1` 日线，范围 2023-01-03 至 2026-07-17。该临时测试库用于真实 Provider 验收，不等同于用户默认开发库；正式使用仍需在目标库显式运行 D01 CLI。

检查时间：2026-07-19。可信验收库为 `alphadesk_sc01_test_20260719`，Alembic `0013_a01`。该库只包含已有 SC01/N01/A01 验收事实，没有为 I01 伪造账户、行情、订单、Fill 或回测结果。

本机原默认开发库 `alphadesk` 当前记录为 `0011_bt01`，来源于此前独立 BT01 分支。当前稳定代码不包含该 revision，因此普通 API 容器会安全失败并报告 `Can't locate revision '0011_bt01'`。I01 不删除、不降级、不覆盖该数据库；它不计入 V0.1 可信基线。

| 功能 | 必需数据 | 最低数量/范围 | 当前验收库状态 | 缺失影响 | 下一阶段解决方式 |
| --- | --- | --- | --- | --- | --- |
| Instrument 目录 | `instruments` | 至少 1；D01 应覆盖目标股票池 | D01 隔离验收：5,537；active 5,200 | 目标开发库未同步时仍无法选择 | 在目标库显式运行 `sync-instruments` |
| 历史行情 | `market_bars` DAY_1 | 每标的按策略/扫描器 lookback，建议至少 250 交易日 | D01 隔离验收：300 标的、256,408 根；2023-01-03–2026-07-17；不足 250 根为 0 | D01-C 前不会自动每日增量 | D01-C 增量；D01-D 完整质量检查 |
| Scanner | Instrument + DAY_1 | 至少 1 个满足规则 lookback 的标的 | 实数验收：两个 Scanner 各扫描 3 只，均 COMPLETED、0 结果 | 目标库无数据时仍只能加载目录 | 先在目标库执行 D01 补数 |
| Strategy | Instrument + DAY_1 | 至少 1 个覆盖所选时间范围的标的 | 实数验收：SMA 处理 129 根、生成 7 个研究 Signal、COMPLETED | 不代表收益或可交易性 | 保持现有研究边界；不自动下单 |
| Strategy Experiment | 同 Strategy，组合数 1–50 | 至少 1 个可运行组合 | Experiment 0 | 不能产生比较结果 | D01 后再做参数实验 |
| Portfolio | SIMULATED account | 至少 1 | 0 | 不能入出金、估值或核对 | 用户手工创建模拟账户或运行既有 demo CLI |
| Orders/Risk | 模拟账户 + Instrument | 各至少 1 | Order 0；RiskDecision 0 | 不能创建受控订单 | D01 后使用模拟账户验收链路 |
| Simulated Broker | 已确认可执行 Order | 至少 1 QUEUED/BROKER_ACCEPTED/PARTIALLY_FILLED | 0；Fill 0 | 无模拟执行入口 | 先完成订单人工确认，不接真实 Broker |
| Information Center | PostgreSQL | 手工录入无需预置；研究需至少 1 Item | Source 7；Item 2；Event 2 | 当前可用 | N01 已满足 |
| AI Research | InformationItem/Event + Provider | 至少 1 Evidence；Provider configured | AIAnalysisRun 3；验收进程使用 Fake | 默认启动配置下不可创建 | 真实 Provider 不属于 I01；Fake 仅本地验收 |
| Backtest | BT01 表、运行服务、历史行情 | 完整 Migration 链与确定性验收 | 当前稳定库无 BT01 表 | 当前分支不可运行 | 后续 BT01-R；数据由 D01 提供 |

## 配置结论

- `ALPHADESK_AI_RESEARCH_PROVIDER` 默认 `disabled`；仅 `fake` 可用于确定性本地验收，没有真实 Provider。
- `ALPHADESK_REALTIME_MARKET_PROVIDER` 固定 `disabled`，免费实时源不是交易级数据。
- `ALPHADESK_FREE_MARKET_DATA_ENABLED` 默认 false；I01 不启动外部 Worker 和网络补数。
- R01 限额来自服务端环境配置；网页只读，不能覆盖。
- 系统无认证，必须仅绑定可信本机回环地址。
