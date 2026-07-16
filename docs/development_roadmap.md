# 开发路线图

> M04.1A is sealed with a disabled real-time provider: BaoStock historical data remains available, but AKShare real-time validation did not pass. A Windows Agent/MiniQMT integration is deferred until after M06; no public deployment or real trading is authorized.

> M04.1A 已完成免费行情工程实现：AKShare/EastMoney 负责全市场快照与重点标的近期分钟线，BaoStock 负责历史日线/分钟线补充；独立 Worker、Redis 临时 Quote、WebSocket 和盘中估值预览均保持 Best-Effort、非交易级。真实来源连接与交易时段 10 分钟验收必须独立记录，未通过时不得宣称行情已接通。

> M04 已实现模拟账户、资金与持仓账本、成交记账、估值、核对和持仓网页；订单状态机、撮合、Broker 与实盘仍属于后续里程碑。

> 2026-07-15 经 M03 任务明确修订：M03 为“行情基础数据、行情适配器与自选股业务闭环”，现已完成。下一个 M04 只允许“账户、资金、持仓与账本”，不得接入 Broker、订单、策略、风控或实盘。本说明取代下方早期表格中 M03/M04 的旧名称；其余远期阶段仍需在进入时重新评审。

## M03 验收状态（完成）

新增 4 张行情表、确定性 DEMO 和受限本地 CSV Adapter、批量幂等 Upsert、同步运行/事件/审计、标的与自选股 API，以及懒加载行情工作台。真实外部行情入口仍禁用；Outbox 发布、Redis Streams、策略、订单和 Broker 均未进入本阶段。

每个里程碑必须通过其验收门槛，且不得提前开启实盘能力。阶段编号用于规划，不代表已完成。

## M04.1A 工程状态

M04.1A 是 M04 之后的受限行情增量，不改变远期阶段的授权顺序。默认配置关闭外部免费行情，核心 CI 只使用 Fake Client；联网验收必须显式启用，且即使通过也只代表免费 Best-Effort 数据可用。该阶段没有 Signal、Order、Fill、撮合、Broker、执行器或实盘能力，也不授权继续实施 M05。

| 阶段 | 目标 | 验收门槛 |
| --- | --- | --- |
| M00（完成） | 架构文档、规则和目录框架 | 文档齐全；无业务代码、依赖或外部连接 |
| M01（完成） | 工程基线、基础网页与配置边界 | 本地 Compose、API/Web 骨架、空迁移、锁定依赖、测试和 CI 已建立；无交易业务或密钥入库 |
| M02（完成） | 领域模型与 PostgreSQL 持久化 | Migration、核心实体、审计与事务边界通过真实 PostgreSQL 集成测试 |
| M03 | 事件与 Transactional Outbox | 同事务写入、重试与幂等消费有自动化测试 |
| M04 | 模拟 Broker 与订单状态机 | 全部合法/非法迁移和模拟成交、取消场景可验证 |
| M05 | 风控与人工确认 | 后端风控、只卖模式、急停、人工确认均不可绕过 |
| M06 | Windows 执行器骨架与可靠回执 | 设备注册、签名、断网恢复、重复回执测试通过 |
| M07 | 行情与持仓只读投影 | 行情时效、持仓快照与审计可追溯；不含实盘 |
| M08 | 策略、信号与扫描器 | 策略仅产生 Signal；策略版本和参数可追溯 |
| M09 | 回测引擎 | 无未来数据泄漏；费用、滑点、交易规则和可复现性测试通过 |
| M10 | Web 控制台 | 只呈现经授权数据；无交易密钥；订单操作受后端控制 |
| M11 | 全球资讯与 AI 分析 | AI 输出可溯源且只产生建议/Signal，不能直接下单 |
| M12 | MiniQMT/XtQuant 只读 Adapter | 只读账户/行情验证、断连处理、对账观察；不下单 |
| M13 | 受控实盘准备演练 | 模拟端到端演练、双层风控、人工确认、急停、对账通过 |
| M14 | 小额人工确认实盘评审 | 明确书面批准、限额/白名单/只卖开关、监控与回滚预案齐备 |

M14 不是自动授权。任何实盘启用都需要单独确认，并应在受控环境中从最小权限和最小金额开始。

## M01.1 补充验收状态（完成）

M01 已完成 Docker Compose 端到端补充验收：四服务健康、在线 Migration、真实 PostgreSQL/Redis 集成测试、浏览器路由与状态展示、单服务故障恢复、整组重启和命名卷持久性均已验证。验收中修复了 Web 容器 IPv4 健康检查，以及 API 镜像缺少测试文件和非 root 缓存写权限的问题。

M01.1 没有新增账户、持仓、行情、策略、风控、订单、Broker、AI 或执行器功能。

## M02 验收状态（完成）

M02 已建立纯 Python 领域包、18 张 PostgreSQL 表、显式映射、异步仓储和 Unit of Work。隔离测试库验证了 Alembic upgrade/downgrade/re-upgrade/check、关键数据库约束、幂等键、Decimal/UTC 往返，以及订单、状态迁移、事件、审计与 Outbox 的同事务提交和强制回滚。M03 的 Outbox 发布器、Redis Streams 与消费者尚未实现。
