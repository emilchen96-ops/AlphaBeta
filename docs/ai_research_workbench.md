# TA01 多智能体 AI 调研工作台

TA01 将 AlphaDesk 的主要 AI 入口收口为一个面向普通用户的调研工作台。页面只要求：

1. 搜索并选择一只 A 股；
2. 输入研究问题；
3. 选择快速、标准或深度调研；
4. 选择资料时间范围；
5. 点击“开始 AI 调研”。

任务创建后由独立 Worker 执行，关闭页面、刷新浏览器或重启 Web 不会中断任务。任务进度页显示当前阶段、各角色状态、失败原因、取消与失败后重试入口；完成后进入结构化报告页，并同步出现在“研究档案”的 AI 调研分类中。

旧 A01 的单事件分析接口和历史详情继续只读兼容，但“分析类型、资讯事实、市场事件”不再出现在主要操作流中。

## 功能边界

- 只读本地 MiniQMT 日线与本地资讯事实；不直接操作 MiniQMT 客户端。
- 不创建研究信号、风控决策、订单、成交或持仓。
- 不执行 TradingAgents CLI，也不依赖 `D:\QTM\TradingAgents`。
- 浏览器不接收、保存或显示 API Key。
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
