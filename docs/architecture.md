# 架构总览

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
- SQLAlchemy metadata 在 M01 为空；Redis Streams、Outbox 和交易领域仍未实现。

## M01.1 运行时验收结论

M01 当前的可运行拓扑已通过真实 Docker Compose 验证：浏览器只访问宿主机回环地址上的 Web 与 API；PostgreSQL 和 Redis 不发布宿主机端口，只能由 Compose 内部网络访问。API 和 Web 均以非 root 用户运行，API 启动前执行幂等的 `alembic upgrade head`。

`/health/live` 与 `/health/ready` 的分离在故障注入中得到验证：依赖中断不会伪装成 API 进程死亡，但会阻止就绪；前端通过系统状态接口展示降级，并通过有上限退避的 WebSocket 重连恢复展示连接。PostgreSQL 的 `alembic_version` 与 Redis AOF 数据均能跨整组容器重启保留在命名卷中。

这些运行时行为仍只属于基础设施探测。Redis 未启用 Streams，PostgreSQL 除 `alembic_version` 外没有业务表，WebSocket 不承载交易命令，架构依赖方向和 M01 领域边界没有改变。
