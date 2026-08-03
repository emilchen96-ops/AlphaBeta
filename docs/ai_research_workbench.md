# TA01 多智能体 AI 调研工作台

TA01 将 AlphaDesk 的主要 AI 入口收口为一个面向普通用户的调研工作台。页面只要求：

1. 搜索并选择一只 A 股；
2. 输入研究问题；
3. 从管理员配置的兼容模型中选择本次调研模型；
4. 选择快速、标准或深度调研；
5. 选择资料时间范围；
6. 点击“开始 AI 调研”。

任务创建后由独立 Worker 执行，关闭页面、刷新浏览器或重启 Web 不会中断任务。任务进度页显示当前阶段、各角色状态、失败原因、取消与失败后重试入口；完成后进入结构化报告页，并同步出现在“研究档案”的 AI 调研分类中。

旧 A01 的单事件分析接口和历史详情继续只读兼容，但“分析类型、资讯事实、市场事件”不再出现在主要操作流中。

## 功能边界

- 股价事实只读本地 MiniQMT 日线；财务、公告、新闻和宏观资料通过可审计工具读取本地资料与显式外部来源。
- 不创建研究信号、风控决策、订单、成交或持仓。
- 运行固定 revision 的 TradingAgents Graph，但不执行其 CLI，也不依赖 `D:\QTM\TradingAgents`。
- 任务页显示 Graph/工具轨迹，报告页显示 12 个角色的独立报告、来源覆盖和完整报告。
- 浏览器不接收、保存或显示 API Key。
- 可选模型由根目录 `.env` 的 `ALPHADESK_AI_SELECTABLE_MODELS` 白名单控制；任务会保存所选模型，失败重试仍沿用原模型。
- Fake Provider 只验收流程，页面和报告必须明确标为非真实 AI 调研。

## API

- `POST /api/v1/ai/research-tasks`
- `GET /api/v1/ai/research-tasks`
- `GET /api/v1/ai/research-tasks/{task_id}`
- `POST /api/v1/ai/research-tasks/{task_id}/cancel`
- `POST /api/v1/ai/research-tasks/{task_id}/retry`
- `GET /api/v1/ai/research-tasks/{task_id}/report`
- `GET /api/v1/ai/reports/{task_id}`
- `GET /api/v1/ai/research-tasks/{task_id}/report/markdown`
- `GET /api/v1/ai/research-tasks/{task_id}/report/pdf`

创建接口返回 `202 Accepted`。相同幂等键和相同请求快照返回原任务；相同键但参数不同会拒绝。

## 真实 Graph 验收基线

2026-08-01 使用 `300115.SZ` 对固定 revision `a33fd4c0f134485a43553a2c23a63cb14adbd88f` 完成同股验收：

- AlphaDesk 与上游 TradingAgents 均覆盖 12/12 个角色；
- AlphaDesk 完成 29 次工具调用，失败 0 次；
- MiniQMT 行情、财务报表、公司公告、新闻、宏观和 A 股市场情绪六类来源全部覆盖；
- Agent 事件、工具调用、12 份独立报告、最终报告和恢复检查点均已持久化。

机器可读和人工可读结果分别保存在 `docs/verification/ta01-same-stock-attempt6.json` 与 `docs/verification/ta01-same-stock-attempt6.md`，可使用 `scripts/compare_ta01_reports.py` 重复验收。

模型服务拒绝请求、达到额度或暂时不可用时，任务必须保留失败原因、当前执行次数和 SQLite Graph 检查点。恢复模型额度后对原任务执行“重试”，Worker 使用同一任务目录继续运行，不得伪造成功报告或回退到旧摘要流程。
