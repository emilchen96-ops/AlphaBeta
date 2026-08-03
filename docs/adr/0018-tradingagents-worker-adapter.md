# ADR 0018：固定上游 TradingAgents Graph 并由独立 Worker 适配运行

- 状态：Accepted
- 日期：2026-08-01

## 决策

TA01 使用固定 Git revision 的 Apache-2.0 TradingAgents Python 包，直接运行其 LangGraph、分析师工具链、多空辩论、交易方案、三方风险讨论与组合经理决策。AlphaDesk 不嵌入上游 CLI，也不依赖开发机 `D:\QTM\TradingAgents` 路径。

Graph 只在独立 `ai_research_worker` 中运行。AlphaDesk 注入独立工具供应商：市场价格只来自本地 MiniQMT 未复权日线；财务、公告、新闻和宏观资料来自本地事实与显式外部工具。每个 Graph/工具事件、角色报告和最终报告持久化到 PostgreSQL，上游 SQLite checkpointer 保存节点级恢复状态。

## 原因

重新模拟角色链会失去 TradingAgents 已实现的工具决策、辩论状态与风险讨论语义，也无法与上游结果做可信对照。固定 revision 能保留真实能力并控制升级风险；独立 Worker、工具边界和持久化审计则满足 AlphaDesk 的安全、恢复和可追溯要求。

## 后果

- 构建环境必须能安装固定的上游归档及其依赖。
- 上游升级必须单独审计、更新 NOTICE、迁移适配器并重新执行同股验收。
- AI 调研耗时和 Token 消耗显著高于旧摘要流程，需使用快速/深度模型、超时、重试和断点恢复。
- 任何工具或角色缺失都必须显式呈现，禁止回退到伪多智能体摘要。
