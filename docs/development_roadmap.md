# 开发路线图

> 2026-07-23：L2.5-A 完成 MiniQMT 只读行情 Provider、Windows Agent、期望/实际订阅事实、
> Redis Quote、WebSocket、D03 分钟 Bar、有限历史补数、API/CLI 和中文页面。该阶段不读取
> 券商账户事实，不提供任何交易能力。下一阶段仅为 **L2.5-B：心跳、重连与行情健康检查**。

> 2026-07-22：D03 已完成实现与验收。系统具备离线历史 1/5/15/30/60 分钟数据导入、
> A股双 Session 聚合、RAW/QFQ 查询、D02 日历/状态/因子质量口径、覆盖度、Readiness、
> 分批查询端口、API、CLI 与页面。当前不是实时行情；BT02、分钟回放、MiniQMT 与实盘均未实现。
> 下一阶段仅为 **BT02：分钟级回测**。

> 2026-07-22：D02 已完成实现与验收。系统新增 SHSE/SZSE 交易日历、复权因子、停复牌与
> Instrument 生命周期事实，并将明确的 RAW/QFQ 语义接入 D01、Scanner、Strategy、BT01 和
> RT01。RAW 仍是模拟成交、费用和账本的唯一权威价格；QFQ 只用于研究与指标。当前默认使用
> 离线 Fixture，真实 Tushare Provider 未配置时不会联网。这是 D02 封板时的历史状态；D03
> 已在其后完成，BT02、MiniQMT 和实盘仍未实现。

> 2026-07-21：RT01 已完成：D01 日线可按 Session 启动、暂停、恢复、单步和倍速回放；
> 独立 Worker、lease 恢复、既有 Strategy/R01/M05/B01/M04 事实链、BT01 一致性、API、CLI、
> WebSocket、页面和 Integrity 均已接入。无 MiniQMT 或实盘能力。下一阶段仅为 **D02：交易日历、
> 复权因子和停复牌数据增强**。

> 2026-07-21：A01-P 真实 Provider Adapter 已完成：OpenAI 兼容 HTTP、服务端 Secret、结构化
> Schema/Evidence 校验、有限重试、usage/成本、状态/API/CLI/页面均已接入。默认 Disabled，
> 未配置 Key 时不访问外网；外部凭据联调未执行。下一阶段仅为 **RT01 历史回放模拟运行**。
> D02、D03、BT02 和 MiniQMT 尚未完成。

> 2026-07-21：U01 已完成实现：一键研究初始化、只读验收、首页能力卡片和开始使用页面。
> 该阶段不包含真实 AI、实时交易行情、分钟回测、MiniQMT 或真实券商执行。

> 2026-07-20：BT01-R 已完成，日线回测支持完成。最新 D01 基线已整合，旧 BT01 仅选择性复用；T+1 开盘、独立账户、事实管道、绩效、Integrity、API、CLI 和页面均已接入。D03 分钟行情、BT02 分钟回测、MiniQMT 和实盘均未开始。下一阶段仅为 **U01：一键初始化与系统可用性收口**。

> 2026-07-19：D01-A/B/C/D/E 已完成，历史行情数据中心封板。系统可同步 A 股与研究池、补数和每日增量、持久化质量事实、计算覆盖率/Readiness，并从 API、CLI 和 React 页面运营；不含实时行情、MiniQMT 或交易写入。下一阶段仅为 BT01-R。

> 2026-07-19：I01 V0.1 集成基线已完成。系统已建立统一功能、动作、API、数据与配置盘点，以及只读 capability 接口；SC01、N01、A01 已完成。BT01 独立提交因 Migration/共享代码冲突未安全并入，保持 PARTIAL。下一步唯一主线是 **D01 历史行情数据中心**，其后才允许 BT01-R。

> 2026-07-19：A01 已完成，包含安全 Provider 端口、版本化 Prompt、AIAnalysisRun、ResearchInsight、Evidence、API、CLI 和 React 页面。默认真实 Provider 禁用，Fake Provider 仅用于测试/本地演示；AI 不创建 Signal、Order、Fill 或账本记录。

> 2026-07-19：N01 已完成，包含手工/RSS输入、原始事实保留、去重、资讯与市场事件、Instrument/主题关联、API、CLI 和页面。N01 不使用 AI，不创建 Signal、订单或账本记录。

> 2026-07-19：SC01 已完成，包含统一 Scanner、两个历史日线规则、持久化、API、CLI 和 React 页面。扫描不会创建 Signal、Order、Fill、RiskDecision 或账本记录。

> 当前进度：B01-A 与 B01-B 已完成开发。系统具备纯领域模拟 Broker、追加式执行尝试、持久化
> Fill、M05 状态推进、M04 原子记账、Command 本地消费和 Outbox 抑制。B01-C 尚未开始，B01 整体
> 尚未完成；当前没有 API、前端、Windows 执行器、MiniQMT、外部 Broker 或实盘能力。详见
> [simulated_broker.md](simulated_broker.md) 与
> [simulated_execution_pipeline.md](simulated_execution_pipeline.md)。

> 2026-07-17：B01-B 完成后端模拟执行事实管道。真实 PostgreSQL/Alembic 集成与并发测试必须在
> 显式启用的独立测试库执行；非数据库单元与静态检查不能替代该验收门槛。

> 2026-07-17：B01-A 完成。模拟 Broker 只根据调用方显式传入的市场/账户快照计算 `FillDraft` 和执行结果，不修改 M04/M05/R01 事实；R01 PASS 不代表一定成交。

> 2026-07-17：R01-C 完成风控决策列表/详情、当前限制只读展示、订单双向关联和 Signal 独立风险评估。REJECT/REVIEW 不创建 Order，Signal 不自动下单。

> 2026-07-16：R01-A 轻量风控核心及 R01-B 决策持久化与 M05 安全门已完成。R01-C 尚未开始；系统仍不接入 Broker/MiniQMT。

> 2026-07-16：S02-A、S02-B1、S02-B2 均已完成，S02 策略研究阶段封板。系统具备策略目录、单次历史研究、批量参数实验、Signal 对比与重合度页面，但仍不计算绩效、不创建订单、不调用风控或 Broker。下一阶段为 R01 轻量风控，尚未实施。

> 2026-07-16：S02-A 与 S02-B1 后端已完成；B1 提供同步批量研究、实验持久化、Signal
> 比较和重合度 API。S02-B2 前端尚未开始，S02 整体尚未完成。

> 2026-07-16：用户决定跳过 S01 最终专项审查并继续策略开发。S01-A、S01-B、S01-C
> 功能开发已完成；S02-A Decimal 增量指标与基础策略库已完成，S02-B 尚未开始。

> 2026-07-16：S01-B 已完成同步历史 StrategyRunner、StrategyRun/Signal 持久化、请求指纹幂等、失败回滚与只读完整性查询。S01-C 及 API、CLI、页面、调度、回测撮合、风控和交易执行均未开始。

> 2026-07-16：S01-A 已完成纯 Python 策略契约；S01-B 已完成历史运行和 Signal 持久化。S01 整体仍未完成，当前没有 API、页面、完整回测、调度、Order 创建或交易执行能力。详见 [strategy_interface.md](strategy_interface.md) 与 [strategy_runner.md](strategy_runner.md)。

> 2026-07-16：M05 订单事实管道已完成并封板。它只在 PostgreSQL 原子创建本地订单/命令/Outbox 事实，不发送、不成交、不改变账本。下一阶段为 S01 统一策略接口：`MarketBar -> Strategy -> Signal -> Signal 持久化和查询页面`；S01 不得直接创建 Order。

> M05-A订单领域模型、状态机和持久化基础已完成；M05应用服务、Transactional Outbox、API、前端和并发验收尚未完成。

> M04.1A is sealed with a disabled real-time provider: BaoStock historical data remains available, but AKShare real-time validation did not pass. A Windows Agent/MiniQMT integration is deferred until after M06; no public deployment or real trading is authorized.

> M04.1A 已完成免费行情工程实现：AKShare/EastMoney 负责全市场快照与重点标的近期分钟线，BaoStock 负责历史日线/分钟线补充；独立 Worker、Redis 临时 Quote、WebSocket 和盘中估值预览均保持 Best-Effort、非交易级。真实来源连接与交易时段 10 分钟验收必须独立记录，未通过时不得宣称行情已接通。

> M04 已实现模拟账户、资金与持仓账本、成交记账、估值、核对和持仓网页；订单状态机、撮合、Broker 与实盘仍属于后续里程碑。

> B01-A、B01-B、B01-C 已完成代码开发：本地确定性模拟 Broker、原子 Fill/账本执行、API、CLI、Demo、订单入口和只读成交页面均已实现。B01 只有在真实 PostgreSQL 并发、在线 Migration、Demo 和浏览器验收通过后才能最终封板。系统未连接真实 Broker、MiniQMT 或实盘；下一阶段仅为 BT01 日线回测。

> 2026-07-15 经 M03 任务明确修订：M03 为“行情基础数据、行情适配器与自选股业务闭环”，现已完成。下一个 M04 只允许“账户、资金、持仓与账本”，不得接入 Broker、订单、策略、风控或实盘。本说明取代下方早期表格中 M03/M04 的旧名称；其余远期阶段仍需在进入时重新评审。

## M03 验收状态（完成）

新增 4 张行情表、确定性 DEMO 和受限本地 CSV Adapter、批量幂等 Upsert、同步运行/事件/审计、标的与自选股 API，以及懒加载行情工作台。真实外部行情入口仍禁用；Outbox 发布、Redis Streams、策略、订单和 Broker 均未进入本阶段。

每个里程碑必须通过其验收门槛，且不得提前开启实盘能力。阶段编号用于规划，不代表已完成。

## M04.1A 工程状态

M04.1A 是 M04 之后的受限行情增量，不改变远期阶段的授权顺序。默认配置关闭外部免费行情，核心 CI 只使用 Fake Client；联网验收必须显式启用，且即使通过也只代表免费 Best-Effort 数据可用。该阶段没有 Signal、Order、Fill、撮合、Broker、执行器或实盘能力，也不授权继续实施 M05。

| 阶段        | 目标                         | 验收门槛                                                                             |
| ----------- | ---------------------------- | ------------------------------------------------------------------------------------ |
| M00（完成） | 架构文档、规则和目录框架     | 文档齐全；无业务代码、依赖或外部连接                                                 |
| M01（完成） | 工程基线、基础网页与配置边界 | 本地 Compose、API/Web 骨架、空迁移、锁定依赖、测试和 CI 已建立；无交易业务或密钥入库 |
| M02（完成） | 领域模型与 PostgreSQL 持久化 | Migration、核心实体、审计与事务边界通过真实 PostgreSQL 集成测试                      |
| M03         | 事件与 Transactional Outbox  | 同事务写入、重试与幂等消费有自动化测试                                               |
| M04         | 模拟 Broker 与订单状态机     | 全部合法/非法迁移和模拟成交、取消场景可验证                                          |
| M05         | 风控与人工确认               | 后端风控、只卖模式、急停、人工确认均不可绕过                                         |
| M06         | Windows 执行器骨架与可靠回执 | 设备注册、签名、断网恢复、重复回执测试通过                                           |
| M07         | 行情与持仓只读投影           | 行情时效、持仓快照与审计可追溯；不含实盘                                             |
| M08         | 策略、信号与扫描器           | 策略仅产生 Signal；策略版本和参数可追溯                                              |
| M09         | 回测引擎                     | 无未来数据泄漏；费用、滑点、交易规则和可复现性测试通过                               |
| M10         | Web 控制台                   | 只呈现经授权数据；无交易密钥；订单操作受后端控制                                     |
| M11         | 全球资讯与 AI 分析           | AI 输出可溯源且只产生建议/Signal，不能直接下单                                       |
| M12         | MiniQMT/XtQuant 只读 Adapter | 只读账户/行情验证、断连处理、对账观察；不下单                                        |
| M13         | 受控实盘准备演练             | 模拟端到端演练、双层风控、人工确认、急停、对账通过                                   |
| M14         | 小额人工确认实盘评审         | 明确书面批准、限额/白名单/只卖开关、监控与回滚预案齐备                               |

M14 不是自动授权。任何实盘启用都需要单独确认，并应在受控环境中从最小权限和最小金额开始。

## D03 增量里程碑（完成）

D03 已在 D01/D02 后建立历史分钟基础设施：1/5/15/30/60 分钟、A股双 Session、离线 CSV/
Fixture、确定性聚合、质量、Readiness、API/CLI/页面。它不改变上表的实盘授权顺序，也不表示
实时行情已连接。下一步仅为 BT02 分钟级回测，尚未实现。

## M01.1 补充验收状态（完成）

M01 已完成 Docker Compose 端到端补充验收：四服务健康、在线 Migration、真实 PostgreSQL/Redis 集成测试、浏览器路由与状态展示、单服务故障恢复、整组重启和命名卷持久性均已验证。验收中修复了 Web 容器 IPv4 健康检查，以及 API 镜像缺少测试文件和非 root 缓存写权限的问题。

M01.1 没有新增账户、持仓、行情、策略、风控、订单、Broker、AI 或执行器功能。

## M02 验收状态（完成）

M02 已建立纯 Python 领域包、18 张 PostgreSQL 表、显式映射、异步仓储和 Unit of Work。隔离测试库验证了 Alembic upgrade/downgrade/re-upgrade/check、关键数据库约束、幂等键、Decimal/UTC 往返，以及订单、状态迁移、事件、审计与 Outbox 的同事务提交和强制回滚。M03 的 Outbox 发布器、Redis Streams 与消费者尚未实现。
