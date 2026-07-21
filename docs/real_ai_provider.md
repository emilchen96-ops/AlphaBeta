# A01-P 真实 AI Research Provider

A01-P 为 AlphaDesk 增加一个通用 `OpenAICompatibleResearchProvider`。它调用服务端配置的
OpenAI 兼容 Chat Completions HTTP 接口，将响应校验为 A01 既有结构化研究对象。它不是 AI
Agent，不执行工具，也不能创建 Signal、RiskDecision、Order、Fill，不能调用 Broker 或
MiniQMT，不能修改现金、持仓或账本。

## 配置与 Secret

默认 Provider 是 `disabled`。所有配置均由 FastAPI 进程从环境变量读取：

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `ALPHADESK_AI_RESEARCH_PROVIDER` | `disabled`、`fake` 或 `openai_compatible` | `disabled` |
| `ALPHADESK_AI_BASE_URL` | Provider API 根地址；代码追加 `/chat/completions` | 空 |
| `ALPHADESK_AI_API_KEY` | Bearer Token，只能保存在本地环境/Secret | 空 |
| `ALPHADESK_AI_MODEL` | Provider 模型标识 | 空 |
| `ALPHADESK_AI_REQUEST_TIMEOUT_SECONDS` | 单次 HTTP 超时 | `30` |
| `ALPHADESK_AI_MAX_RETRIES` | 临时错误重试次数，最多 3 | `1` |
| `ALPHADESK_AI_MAX_INPUT_CHARACTERS` | 本次研究总输入字符上限 | `50000` |
| `ALPHADESK_AI_MAX_OUTPUT_TOKENS` | Provider 最大输出 Token | `2000` |
| `ALPHADESK_AI_TEMPERATURE` | 研究输出温度 | `0.1` |
| `ALPHADESK_AI_COST_INPUT_PER_MILLION` | 每百万输入 Token 的 USD 价格，可空 | 空 |
| `ALPHADESK_AI_COST_OUTPUT_PER_MILLION` | 每百万输出 Token 的 USD 价格，可空 | 空 |
| `ALPHADESK_AI_STRUCTURED_OUTPUT_ENABLED` | 发送 JSON Schema 结构化输出约束 | `true` |

将 `.env.example` 复制为被 Git 忽略的 `.env`，只在 `.env` 写真实 Key。不要使用 `VITE_`
前缀；`VITE_` 值会进入浏览器。Base URL 会拒绝用户密码、query 和 fragment；状态接口仅显示
origin，不显示可能含租户标识的路径。API Key 不进入请求/响应 Schema、数据库或分析 Prompt，
也不记录 Authorization Header。

兼容服务对结构化输出字段的支持可能不同。若服务不支持 `json_schema`，可以显式将
`ALPHADESK_AI_STRUCTURED_OUTPUT_ENABLED=false`，此时仍要求 JSON object，并继续执行完全相同的
本地严格 Schema 和 Evidence 校验。

## Provider 状态与连通性

`GET /api/v1/ai/providers/status` 区分：

- `DISABLED`：默认关闭；
- `FAKE`：确定性测试/演示，不是真实模型；
- `REAL_CONFIGURED`：配置完整，但本进程尚未成功连通；
- `REAL_AVAILABLE`：本进程最近一次调用或测试成功；
- `REAL_UNAVAILABLE`：配置不完整或最近调用失败。

在 development/test 环境可以执行受控小请求：

```powershell
docker compose exec api python -m alphadesk_api.cli.ai provider-status
docker compose exec api python -m alphadesk_api.cli.ai test-provider
```

也可在 AI 研究页点击“测试真实 Provider 连通性”，对应
`POST /api/v1/ai/providers/test`，Body 必须是空对象 `{}`。客户端不能临时指定 Base URL、模型
或 Key。该检查只读取一个短确认响应，返回延迟和稳定错误码，不创建 AIAnalysisRun、
ResearchInsight 或 Evidence，也不返回模型原始内容。生产环境默认禁止该 HTTP 测试入口。

## Prompt 与不可信输入边界

Prompt 契约为 `alphadesk_research_grounded` v1.1.0。系统消息固定强调只分析所选资料、不得泄露
Secret、不得使用工具、不得交易。InformationItem、MarketEvent 派生文本和用户问题只放入 user
消息的 `BEGIN_UNTRUSTED_RESEARCH_DATA` / `END_UNTRUSTED_RESEARCH_DATA` 边界，绝不拼入系统
指令。输入超限时进行确定性截断，并把 `AI_INPUT_TRUNCATED:<source-id>` warning 保存到结构化
输出和 uncertainties。

这是基础隔离和输出约束，不宣称可以完全防御所有 Prompt 注入。使用者仍需核对原始证据。

## 结构化输出与 Evidence

Provider 输出必须是 JSON 对象，或是单一完整的 `json` Markdown 代码块。系统不使用正则修补
破损 JSON。未知字段固定拒绝，因此模型不能夹带 `order`、`trade`、任意 HTTP 请求等字段。
本地 Pydantic Schema 校验：

- schema 版本、summary、entities、instruments、themes；
- impact_direction 受控枚举；
- importance_score 为 0–100，confidence 为 0–1；
- key_facts、uncertainties、research_questions；
- 至少一个 evidence_reference，且每项只能引用一个本次输入中的 InformationItem 或
  MarketEvent。

非法 JSON、Schema 越界或伪造来源分别产生稳定错误码。分析运行最终为 FAILED，不保存部分
ResearchInsight 或 ResearchEvidence，也不保存原始 Provider 错误响应。

## Token、成本与重试

Provider 返回 usage 时，保存 input、output 和 total Token。若没有 total，但有 input/output，
系统只计算二者之和；若 Provider 没有 usage，字段保持空值，不伪造精确 Token。

配置两项每百万 Token 的 USD 单价后：

`estimated_cost = (input_tokens × input_price + output_tokens × output_price) / 1,000,000`

计算全程使用 `Decimal`。页面标记“估算成本（非账单）”；usage 或价格缺失时成本为空。

仅 429、502、503、504、网络超时和临时连接错误按指数延迟有限重试。401、403、其他 HTTP
错误、非法配置、JSON/Schema/Evidence 失败均不重试。默认只重试一次，不会退回 Fake 冒充成功。

## 运行真实研究

确认状态为 `REAL_AVAILABLE` 后，在 `/ai-research` 选择至少一条资讯或市场事件，再发起四种既有
分析类型之一。命令行示例：

```powershell
docker compose exec api python -m alphadesk_api.cli.ai analyze `
  --analysis-type EVENT_SUMMARY `
  --event-id <uuid> `
  --idempotency-key <unique-key>
```

相同幂等键和相同指纹直接返回已存在运行，不重复收费调用。详情页显示 REAL/FAKE、实际
Provider 和模型、Prompt 版本、Token、估算成本、Evidence 和 uncertainties。所有结果继续显示
“AI生成，仅供研究参考。”，没有一键转订单或自动交易入口。

仓库默认测试全部使用 MockTransport 或 Fake，不访问真实互联网。真实 Key 未配置时，只能判定
“代码完成，外部凭据联调未执行”，不能把 Mock 结果宣称为真实连接成功。
