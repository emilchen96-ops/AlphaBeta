# TA01 多智能体调研流程

AlphaDesk 借鉴 TradingAgents 的角色分工、辩论和风险复核思想，但重新实现为本项目的领域对象、持久化任务与 Worker，不复制其 CLI 编排，也不形成运行时依赖。

## 角色与深度

| 深度 | 角色 |
| --- | --- |
| 快速 | 技术面、资讯与事件、风险复核、研究经理 |
| 标准 | 市场环境、技术面、基本面、资讯与事件、风险复核、研究经理 |
| 深度 | 标准角色，加看多研究员与看空研究员 |

每个角色使用固定系统提示词和严格 JSON Schema。输入资料被视为不可信数据；角色只能引用本次输入中存在的 `source_id`。任何未知引用都会令该角色失败，不能进入报告来源清单。

## 持久化状态机

`CREATED → PREPARING_DATA → RUNNING_AGENTS → DEBATING → RISK_REVIEW → GENERATING_REPORT → COMPLETED/PARTIALLY_COMPLETED`

异常终态为 `FAILED`，用户取消为 `CANCELED`。各角色步骤单独保存为 `PENDING/RUNNING/COMPLETED/FAILED/SKIPPED`。Worker 只认数据库事实；已经完成的步骤不会重复调用模型，卡在非终态且超过租约时间的任务可被重新领取。失败任务可由用户重新入队。

## 数据准备

Worker 读取所选股票、指定时间范围内的 MiniQMT 本地未复权日线，以及已落库的关联资讯。没有本地日线时明确失败，并提示先在数据中心补齐；不会静默切换外部行情源。

## 部分成功

只要至少一个角色成功，系统即可生成带局限说明的 `PARTIALLY_COMPLETED` 报告。失败角色、错误摘要和缺失章节会保留；所有角色都失败才将任务标记为 `FAILED`。
