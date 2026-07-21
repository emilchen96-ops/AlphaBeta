# I01 API 契约盘点

> U01 新增开发/测试专用 `/api/v1/demo/initialize-research`、`/demo/research-status` 与
> `/demo/verify-research`；`/system/capabilities` 新增 `availability`、`provider`、`mode`、
> `last_success_at`，同时保留原有字段兼容前端。

FastAPI OpenAPI 生成结果包含 77 个 HTTP path；前端只使用现有 `apps/web/src/api` 客户端，没有第二套客户端。I01 新增一个只读接口：`GET /api/v1/system/capabilities`。

## 前端调用与 OpenAPI 对应

| 客户端 | 方法与路径 | OpenAPI | 结论 |
| --- | --- | --- | --- |
| `system.ts` | `GET /system/status`、`GET /system/capabilities` | 存在 | 一致 |
| `market.ts` | `GET /instruments`、`GET/POST/PATCH/DELETE /watchlists*` | 存在 | 一致 |
| `market.ts` | `GET /market-data/sources`、`GET /market-data/bars`、`GET /market-data/quotes/latest`、`GET /market-data/realtime/status` | 存在 | 一致 |
| `accounts.ts` | `GET/POST /accounts`、`GET /accounts/{id}/summary|live-summary` | 存在 | 一致 |
| `accounts.ts` | `POST deposits|withdrawals|valuation-snapshots|reconciliations` 及账本/快照/核对 GET | 存在 | 一致 |
| `orders.ts` | `GET/POST /orders`、`GET timeline`、`POST confirm|cancel` | 存在 | 一致 |
| `orders.ts` | `POST simulated-executions`、Attempts/Fill/integrity GET | 存在 | 一致 |
| `risk.ts` | Decision/limits GET、Signal assessment POST | 存在 | 一致 |
| `strategies.ts` | Catalog、StrategyRun、Signal、StrategyExperiment 全部调用 | 存在 | 一致 |
| `scanners.ts` | Catalog、ScanRun、results GET/POST | 存在 | 一致 |
| `information.ts` | Sources、manual、items、events GET/POST | 存在 | 一致 |
| `aiResearch.ts` | Provider、analyses、insights GET/POST | 存在 | 一致 |
| `replays.ts` | Replay 创建/列表/详情/控制/state/equity/events/交易事实/integrity | 存在 | 一致 |
| WebSocket | `/ws/system`、`/ws/v1/market-data`、`/ws/replays/{id}` | 应用显式注册 | 一致 |

## 通用契约结论

- Decimal：金额、价格、数量、比例在 Pydantic DTO/TypeScript 类型中保持字符串；没有新增 float 转换。
- UTC：API 使用带时区 `datetime`，前端在提交本地时间控件时调用 `toISOString()`。
- 分页：领域列表统一使用 `items/page/page_size/total`；个别固定小列表按数组返回，前端类型与之匹配。
- 错误：`ApiError` 读取统一 `error.code/message/details/correlation_id/timestamp`；409、422 与 404 不会被伪装成成功。
- Correlation ID：HTTP 响应和错误信封均保留，批量研究错误区会显示链路标识。
- CORS：默认同时允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`。

## 后端存在但前端未覆盖的核心只读/运维接口

- `/health/live`、`/health/ready`：供容器/运维探测。
- Instrument 详情、market latest/sync-runs/subscriptions：当前页面未逐项呈现。
- Account 详情、transactions、positions、latest reconciliation：页面主要通过 summary 聚合读取。
- Scanner/Information/AI integrity：CLI 或详情专项检查使用，前端未全部显示。
- Information source RSS ingest：当前网页只支持手工录入；CLI 可显式摄取。

这些未使用接口均有后端用途，不构成前端断线。当前没有发现调用不存在 API、HTTP method 错位、DTO 字段错位或分页字段错位的 BROKEN 项。

## I01 能力接口

`GET /api/v1/system/capabilities` 只读聚合实现状态、当前数据计数和安全配置状态。它不返回连接串、密码、Token 或 Secret，不修改业务表；数据库不可用时返回 UNKNOWN/MISSING，而不是固定成功或前端伪造状态。
