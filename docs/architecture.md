# 架构总览

> RT01 增量：API 保存控制动作，独立 `replay_worker` 用 PostgreSQL lease 逐 Session 推进；
> Redis 只保存心跳和已提交事件通知。RT01 与 BT01 共用 `HistoricalSessionProcessor`、T+1 时间
> 边界和绩效口径，并复用既有交易事实表。订单外发固定抑制为 `REPLAY_ENGINE`。详见
> [historical_replay.md](historical_replay.md)、[replay_control_model.md](replay_control_model.md) 和
> [replay_worker.md](replay_worker.md)。

```mermaid
flowchart LR
  UI[Replay UI / CLI] --> API[FastAPI control]
  API --> PG[(PostgreSQL replay facts)]
  Worker[replay_worker] --> Lease[Run lease + cursor]
  Lease --> Clock[Shared historical Session processor]
  Clock --> Pipeline[Strategy → Risk → Order → Fill → Ledger]
  Pipeline --> PG
  PG --> WS[DB sequence WebSocket]
  Worker -. heartbeat / notify .-> Redis[(Redis)]
  Pipeline -. SUPPRESSED .-> External[MiniQMT / Broker]
```

> BT01-R 增量：同步回测服务只读取 D01 PostgreSQL 日线，按 `SESSION_OPEN → SESSION_CLOSE → SESSION_END` 驱动既有 Strategy、R01、M05、B01 与 M04。每个运行拥有独立 BT01 模拟账户；回测订单 Outbox 固定为 `SUPPRESSED/BACKTEST_ENGINE`，不会进入 Redis Publisher、Windows Agent、MiniQMT 或券商。详见 [daily_backtest.md](daily_backtest.md) 与 [ADR 0017](adr/0017-deterministic-daily-backtest-pipeline.md)。

```mermaid
flowchart LR
  D01[(D01 MarketBar)] --> Clock[BacktestClock]
  Clock --> Strategy[Strategy]
  Strategy --> Signal[Signal]
  Signal --> Risk[R01 RiskDecision]
  Risk --> Order[M05 Order]
  Order --> Broker[B01 SimulatedBroker]
  Broker --> Fill[Fill]
  Fill --> Ledger[M04 Ledger]
  Ledger --> Result[Equity / Metrics / Integrity]
  Order -. SUPPRESSED .-> Outbox[(PostgreSQL Outbox)]
```

> A01 增量：FastAPI 只把用户选定的 N01 InformationItem/MarketEvent 交给配置驱动的 `AIResearchProvider`。版本化 Prompt 将外部文本视为不可信数据，结构化输出必须引用本次输入 Evidence；PostgreSQL 保存 AIAnalysisRun、ResearchInsight 和 ResearchEvidence。默认 Provider 为 disabled，Fake 仅用于测试/本地演示，当前没有真实 Provider。A01 不调用 Scanner、Risk、Broker 或 MiniQMT，不创建 Signal、Order、Fill，也不修改资金和持仓。详见 [ai_research_assistant.md](ai_research_assistant.md)。

```mermaid
flowchart LR
  Facts[InformationItem / MarketEvent] --> Run[AIAnalysisRun]
  Run --> Provider[Disabled / Fake AIResearchProvider]
  Provider --> Validate[版本化结构与 Evidence 校验]
  Validate --> Insight[ResearchInsight + ResearchEvidence]
  Insight --> UI[只读研究页面]
  Insight -.禁止.-> Trade[Signal / Risk / Order / Fill / Broker / MiniQMT]
```

> N01 增量：手工输入或 RSS/Atom Adapter 只产生来源、原始文档、规范资讯、市场事件和关联事实；PostgreSQL 是唯一事实来源。N01 不调用 AI、Scanner、Strategy、Risk 或 Broker，不创建 Signal/Order，也不写账本。详见 [information_center.md](information_center.md)。

```mermaid
flowchart LR
  Input[手工文本 / RSS Fixture或手工抓取] --> Raw[RawDocument 原文事实]
  Raw --> Normalize[规范化 + SHA-256 去重]
  Normalize --> Item[InformationItem]
  Item --> Event[MarketEvent]
  Event --> Links[Instrument / Theme 关联]
  Links --> UI[资讯与事件页面]
  Event -.禁止.-> Trade[AI / Signal / Risk / Order / Broker / Ledger]
```

> SC01 增量：浏览器通过 FastAPI 手工发起历史日线筛选；应用服务从 PostgreSQL 读取既有 MarketBar，将纯 Python Scanner 的匹配结果作为 ScanRun/ScanResult 保存。该链路不使用 Redis，不创建 Signal、RiskDecision、Order 或 Fill，不调用 Broker，也不修改账户和账本。详见 [scanners.md](scanners.md)。

## SC01 历史扫描链路

```mermaid
flowchart LR
  UI[React 扫描表单] --> API[FastAPI ScannerRunService]
  API --> PG[(PostgreSQL MarketBar)]
  API --> Core[纯 Python Scanner]
  Core --> Facts[ScanRun + ScanResult]
  Facts --> PG
  Facts --> UI
  Core -.禁止.-> Trading[Signal / Risk / Order / Broker / Ledger]
```

> M05 状态：Web/FastAPI 已具备本地手工订单事实管道。确认事务只写 PostgreSQL 的 Action、Transition、Command、Event、Audit 与 PENDING Outbox；没有 Publisher、Redis 订单流、执行器、Broker、Fill 或实盘。QUEUED 不等于已发送。

> The real-time market provider is currently `disabled`; historical prices cannot act as real-time prices. MiniQMT can only arrive through a Windows Agent after M06. There is no real-trading capability and this system must not be publicly deployed.

> M04.1A 新增独立 `market_worker`：PostgreSQL 保存来源、K 线和运行审计；Redis 保存可重建的最新 quote、leader 租约、状态及 UI Pub/Sub；FastAPI 只运行共享 Redis listener 和只读 HTTP/WebSocket 接口，不在 lifespan 抓取外部行情。

> M04 架构增量：FastAPI 应用服务在单个 PostgreSQL 事务内追加资金/持仓账本并更新投影；估值复用 M03 行情查询；Redis 不承载权威账户数据。详见 `accounting.md` 与 ADR 0011。

## M03 行情切片

行情切片遵守 `Web → FastAPI → 应用服务 → 领域端口 → 基础设施` 的单向依赖。PostgreSQL 保存来源、映射、K 线、同步运行、事件和审计；Redis 在 M03 仍不承载行情事实、缓存或消息。详细边界见 [market_data.md](market_data.md) 与 ADR 0008。

AlphaDesk 的 MVP 采用模块化单体：业务规则集中于单一后端代码库，并通过清晰的领域与适配器边界隔离外部依赖。Windows 执行器是独立进程和安全边界，不是 Web 后端的一个远程函数。

## 总体系统

```mermaid
flowchart LR
  Web[React + TypeScript Web] <-->|HTTPS / WebSocket 展示| API[FastAPI 模块化单体]
  API --> Domains[领域模块\n账户 / 持仓 / 策略 / 信号 / 风控 / 订单 / 成交 / 事件 / 审计]
  API --> PG[(PostgreSQL\n唯一事实来源)]
  API --> Redis[(Redis\n缓存、Streams、短期状态)]
  Worker[后台 Worker] --> PG
  Worker --> Redis
  Redis <-->|可靠命令与回执 Streams| Agent[Windows 本地交易执行器]
  Agent --> Sim[模拟 Broker]
  Agent -.未来、受控.-> QMT[MiniQMT/XtQuant Adapter]
  QMT -.-> Broker[券商账户]
```

## 前端、后端、数据与执行器关系

```mermaid
flowchart TB
  UI[浏览器] -->|身份认证后的 HTTPS| API[FastAPI API]
  API -->|查询与同事务写入| PG[(PostgreSQL)]
  API -->|缓存、实时投影、Streams| R[(Redis)]
  API -->|WebSocket 仅实时展示| UI
  Outbox[Outbox 发布器] -->|读取待发布事实| PG
  Outbox -->|XADD 命令| R
  R -->|Consumer Group| EA[执行器]
  EA -->|幂等回执| R
  Reconcile[回执/对账处理] --> PG
```

WebSocket 仅用于浏览器展示和订阅，不能作为交易命令可靠通道。订单和 Outbox 必须在同一个 PostgreSQL 事务中创建；Redis 或执行器短暂不可用时，事实仍保留在 PostgreSQL 中。

## 模拟盘链路

```mermaid
sequenceDiagram
  participant S as Strategy
  participant R as Backend Risk
  participant O as Order State Machine
  participant DB as PostgreSQL + Outbox
  participant E as Windows Executor
  participant B as Simulated Broker
  S->>R: Signal
  R->>O: allow / reject
  O->>DB: 订单与 Outbox 同事务写入
  DB->>E: Redis Stream 命令
  E->>E: 最终风控与幂等校验
  E->>B: submit / cancel
  B-->>E: 接受、成交或拒绝
  E-->>DB: 回执事件，状态机持久化
```

## 未来实盘链路

```mermaid
flowchart LR
  Signal --> BackendRisk[后端风控]
  BackendRisk --> Confirm{人工确认\n小额实盘？}
  Confirm -- 否 --> Reject[拒绝并审计]
  Confirm -- 是 --> Order[订单 + Outbox]
  Order --> Stream[Redis Streams]
  Stream --> FinalRisk[Windows 执行器最终风控]
  FinalRisk -- 拒绝 --> Audit[拒绝回执与审计]
  FinalRisk -- 通过 --> Adapter[MiniQMT/XtQuant Adapter]
  Adapter --> Broker[券商]
  Broker --> Reconcile[成交回报与对账]
```

## 依赖方向

```mermaid
flowchart LR
  Apps[apps: API/Web/Worker/执行器] --> Domain[domain: 业务规则]
  Apps --> Adapters[adapters: 外部系统端口实现]
  Adapters --> Infra[infrastructure: DB/Redis/安全/配置]
  Infra --> External[PostgreSQL / Redis / Broker / 行情源]
  Domain -.禁止依赖.-> Apps
  Domain -.禁止依赖.-> Infra
  Domain -.禁止依赖.-> External
```

领域模块通过抽象端口表达所需能力；具体 Broker、FastAPI、Redis 与数据库实现只能位于应用、适配器或基础设施层。

## M01 已实现边界

M01 只实现应用外壳与依赖探测：

```mermaid
flowchart LR
  Browser[React 管理后台] -->|GET /api/v1/system/status| API[FastAPI 应用工厂]
  Browser <-->|/ws/system\n展示连接 ping/pong| API
  API -->|SELECT 1| PG[(PostgreSQL)]
  API -->|PING| Redis[(Redis)]
  API --> Logs[JSON 结构化日志\nCorrelation ID]
  Alembic[空 bootstrap Migration] --> PG
```

- `/health/live` 只验证进程，不访问 PostgreSQL 或 Redis。
- `/health/ready` 对两个关键依赖执行有超时的检查，失败返回 503。
- `/api/v1/system/status` 只返回脱敏后的服务状态、版本、环境和链路 ID。
- `/ws/system` 仅验证实时展示连接，不发送 Signal、订单或执行器命令。
- M01 封板时 SQLAlchemy metadata 为空；Redis Streams、Outbox 发布和交易流程均未实现。

## M01.1 运行时验收结论

M01 当前的可运行拓扑已通过真实 Docker Compose 验证：浏览器只访问宿主机回环地址上的 Web 与 API；PostgreSQL 和 Redis 不发布宿主机端口，只能由 Compose 内部网络访问。API 和 Web 均以非 root 用户运行，API 启动前执行幂等的 `alembic upgrade head`。

`/health/live` 与 `/health/ready` 的分离在故障注入中得到验证：依赖中断不会伪装成 API 进程死亡，但会阻止就绪；前端通过系统状态接口展示降级，并通过有上限退避的 WebSocket 重连恢复展示连接。PostgreSQL 的 `alembic_version` 与 Redis AOF 数据均能跨整组容器重启保留在命名卷中。

这些是 M01.1 封板时的运行时结论。M02 随后增加了 PostgreSQL 领域表，但 Redis 仍未启用 Streams，WebSocket 仍不承载交易命令，既有运行边界没有改变。

## M02 领域与持久化分层

M02 新增独立的 `alphadesk_domain` 纯 Python 包，以及位于 `alphadesk_api.infrastructure` 的 SQLAlchemy Model、Mapper、Repository 和 Unit of Work。依赖只允许从 API/基础设施指向领域协议；领域包不得导入 FastAPI、SQLAlchemy、Redis、XtQuant 或具体 Broker。PostgreSQL 现包含 18 张核心表，结构见 `database_schema.md`。

这一阶段没有增加公开业务 API、网页功能、Redis Streams、Outbox 发布器、订单状态机服务、风控执行或 Broker 调用。Web 与既有健康接口的 M01 行为保持不变。
