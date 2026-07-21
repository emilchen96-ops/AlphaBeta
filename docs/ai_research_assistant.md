# A01 AI 研究助手

A01 建立一条有来源边界、可审计且与交易执行隔离的研究链路：

`InformationItem / MarketEvent → AIAnalysisRun → ResearchInsight → ResearchEvidence`

所有 AI 内容必须显示“AI生成，仅供研究参考。”。研究输出不构成投资建议，不创建 Signal、RiskDecision、Order、Fill，不修改资金、持仓或账本，也不调用 Scanner、Broker、MiniQMT。

## Provider 状态

- `disabled`：默认 Provider；不调用任何真实模型，运行会留下脱敏的 FAILED 审计记录且不会生成部分 Insight。
- `fake`：确定性的测试/本地演示 Provider；由 `ALPHADESK_AI_RESEARCH_PROVIDER=fake` 显式启用。
- `openai_compatible`：A01-P 的真实 Chat Completions HTTP Adapter。Base URL、Key 和模型只由
  服务端环境配置；状态和操作见 [真实 AI Provider](real_ai_provider.md)。

浏览器和 POST 请求都不能传 API Key、Provider Secret、券商账号、Order、Signal 或交易数量。

## 领域与安全契约

Prompt 模板键为 `alphadesk_research_grounded`，版本 `1.1.0`，输出 schema 版本为 `1`。外部文档始终作为不可信数据处理；Provider 只能分析选定来源，必须声明不确定性并引用本次输入中的 InformationItem 或 MarketEvent。

支持四类一次性研究：

- `EVENT_SUMMARY`
- `INSTRUMENT_IMPACT`
- `MULTI_EVENT_SYNTHESIS`
- `RESEARCH_QUESTION`

Fingerprint 包含 Provider、模型、分析类型、Prompt 版本、稳定排序的文档/事件/Instrument ID、规范化问题和 schema 版本。相同幂等键与指纹直接返回原运行；冲突返回 `AI_ANALYSIS_IDEMPOTENCY_CONFLICT`。只有明确的临时 Provider 错误最多重试一次。

非法 schema 或越界 Evidence 会将运行标记 FAILED；完整堆栈、密钥和连接串不会写入分析错误，且不会留下 ResearchInsight 或 ResearchEvidence。

## API 与 CLI

API：

- `GET /api/v1/ai/providers/status`
- `POST /api/v1/ai/providers/test`（仅 development/test）
- `POST /api/v1/ai/analyses`
- `GET /api/v1/ai/analyses`
- `GET /api/v1/ai/analyses/{analysis_id}`
- `GET /api/v1/research-insights`
- `GET /api/v1/research-insights/{insight_id}`
- `GET /api/v1/ai/analyses/{analysis_id}/integrity`

CLI：

```text
python -m alphadesk_api.cli.ai provider-status
python -m alphadesk_api.cli.ai test-provider
python -m alphadesk_api.cli.ai analyze --analysis-type EVENT_SUMMARY --information-item-id <uuid> --idempotency-key <key>
python -m alphadesk_api.cli.ai list
python -m alphadesk_api.cli.ai show --analysis-id <uuid>
python -m alphadesk_api.cli.ai verify-integrity --analysis-id <uuid>
```

前端入口为 `/ai-research`，运行详情为 `/ai-analyses/{id}`，Insight 目录与证据详情为 `/research-insights` 和 `/research-insights/{id}`。页面明确区分原始来源、AI 摘要/推断和不确定性，并提供返回 N01 原始事实的链接。

真实响应的 usage 保存 input/output/total Token；配置 USD 每百万 Token 单价后，以 Decimal 计算
估算成本。Provider 不返回 usage 时相关字段保持为空。该金额仅为估算值，不是账单。

## 持久化与完整性

Migration `0013_a01_ai_research.py` 新增 `ai_analysis_runs`、`research_insights`、`research_evidence`。Evidence 必须且只能关联一个已有 InformationItem 或 MarketEvent；数据库约束保护分数范围、状态、Token/成本非负、版本和唯一幂等键。

`AIResearchIntegrityService` 检查完成运行有 Insight、失败运行无部分 Insight、Evidence 属于本次输入、Prompt 版本、关联关系和 Token 数量。A01 模型没有 Order、Fill、Broker 或账户外键。
