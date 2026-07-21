# I01 数据与配置就绪度

> U01 提供两种研究准备方式：`existing-data` 只使用 D01 本地研究池，数据不足时明确返回
> `NOT_READY`；`fixture` 生成带 `U01_DEMO` 标记的 260 条确定性日线用于功能验收。
> 两种模式都不会在初始化期间访问外部网络。

> BT01-R 已完成：`backtest_daily` Readiness 继续由 D01 覆盖率提供，运行服务还会对请求时间范围内每个标的的实际日线和全局规模上限做权威校验。READY/PARTIAL 描述数据覆盖，不代表实时性，也不授权真实交易。

> D01 完成（2026-07-19）：除 A/B 历史补数外，已具备每日增量、追加式质量运行、覆盖率和按能力最低 K 线要求计算的 Readiness。页面和 `/system/capabilities` 分开报告历史数据状态与 BT01 代码状态；数据 READY 只表示满足历史数据门槛，不代表任何收益或实盘可用性。

检查时间：2026-07-21。当前权威迁移链为 `0014_d01 → 0015_bt01 → 0016_rt01`，只有一个 Alembic head。原默认开发库遗留的旧 `0011_bt01` 五张空回测表已在验收时移除，版本恢复到真实父节点后顺序升级；账户、行情、订单等其他业务数据未删除。独立测试库已验证空库升级、回退及再次升级。

| 功能 | 必需数据 | 最低数量/范围 | 当前验收库状态 | 缺失影响 | 下一阶段解决方式 |
| --- | --- | --- | --- | --- | --- |
| Instrument 目录 | `instruments` | 至少 1；D01 应覆盖目标股票池 | D01 隔离验收：5,537；active 5,200 | 目标开发库未同步时仍无法选择 | 在目标库显式运行 `sync-instruments` |
| 历史行情 | `market_bars` DAY_1 | 每标的按能力 lookback；回测默认至少 250 根 | D01 隔离验收：300 标的、256,408 根；2023-01-03–2026-07-17；不足 250 根为 0 | 目标库未执行增量时会逐日陈旧 | 使用 D01-C update-daily 与 D01-D verify-quality |
| Scanner | Instrument + DAY_1 | 至少 1 个满足规则 lookback 的标的 | 实数验收：两个 Scanner 各扫描 3 只，均 COMPLETED、0 结果 | 目标库无数据时仍只能加载目录 | 先在目标库执行 D01 补数 |
| Strategy | Instrument + DAY_1 | 至少 1 个覆盖所选时间范围的标的 | 实数验收：SMA 处理 129 根、生成 7 个研究 Signal、COMPLETED | 不代表收益或可交易性 | 保持现有研究边界；不自动下单 |
| Strategy Experiment | 同 Strategy，组合数 1–50 | 至少 1 个可运行组合 | Experiment 0 | 不能产生比较结果 | D01 后再做参数实验 |
| Portfolio | SIMULATED account | 至少 1 | 0 | 不能入出金、估值或核对 | 用户手工创建模拟账户或运行既有 demo CLI |
| Orders/Risk | 模拟账户 + Instrument | 各至少 1 | Order 0；RiskDecision 0 | 不能创建受控订单 | D01 后使用模拟账户验收链路 |
| Simulated Broker | 已确认可执行 Order | 至少 1 QUEUED/BROKER_ACCEPTED/PARTIALLY_FILLED | 0；Fill 0 | 无模拟执行入口 | 先完成订单人工确认，不接真实 Broker |
| Information Center | PostgreSQL | 手工录入无需预置；研究需至少 1 Item | Source 7；Item 2；Event 2 | 当前可用 | N01 已满足 |
| AI Research | InformationItem/Event + Provider | 至少 1 Evidence；Provider configured | AIAnalysisRun 3；验收进程使用 Fake | 默认启动配置下不可创建 | 真实 Provider 不属于 I01；Fake 仅本地验收 |
| Backtest | BT01 表、运行服务、D01 历史行情 | 所选标的在时间范围内均有 DAY_1 数据，且不超过 instruments/bars/sessions 上限 | BT01-R 已接入；实际运行仍取决于目标库数据 | 数据不足时返回明确错误，不静默截断 | 先执行 D01 补数、增量更新与质量检查 |

## 配置结论

- `ALPHADESK_AI_RESEARCH_PROVIDER` 默认 `disabled`；`fake` 用于确定性本地验收，A01-P 的
  `openai_compatible` 只有在服务端配置本地 Secret 并通过连通测试后才显示真实可用。
- `ALPHADESK_REALTIME_MARKET_PROVIDER` 固定 `disabled`，免费实时源不是交易级数据。
- `ALPHADESK_FREE_MARKET_DATA_ENABLED` 默认 false；I01 不启动外部 Worker 和网络补数。
- R01 限额来自服务端环境配置；网页只读，不能覆盖。
- 系统无认证，必须仅绑定可信本机回环地址。
