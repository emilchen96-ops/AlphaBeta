# TA01 多智能体调研流程

AlphaDesk 通过固定 revision 的 Apache-2.0 `TradingAgents` Python 依赖运行其真实 LangGraph，保留分析师工具调用、看多/看空辩论、交易方案、三方风险讨论和组合经理决策。它运行在 AlphaDesk 独立 Worker 中，不启动上游 CLI，也不依赖开发机的 `D:\QTM\TradingAgents` 目录。

同股验收可使用 `scripts/compare_ta01_reports.py`，逐项比较十二份独立角色报告、工具调用、来源编号和最终报告覆盖率；该工具不评价投资结论是否相同，只验证两条执行链是否具备同等级的结构与可追溯证据。

## 角色与深度

| 深度 | 角色 |
| --- | --- |
| 快速 | 完整 12 角色链，使用快速模型、1 轮多空与风险讨论 |
| 标准 | 完整 12 角色链，使用配置的标准/深度模型、1 轮讨论 |
| 深度 | 完整 12 角色链，使用深度模型并增加多空与风险讨论轮次 |

12 个持久化角色依次为市场、情绪、新闻、基本面分析师，看多/看空研究员、研究经理、交易方案研究员，积极/中性/保守风险分析师和组合经理。每个独立 Markdown 报告、Graph 节点事件、工具调用输入/输出摘要和来源编号都会落库。

## 持久化状态机

`CREATED → PREPARING_DATA → RUNNING_AGENTS → DEBATING → RISK_REVIEW → GENERATING_REPORT → COMPLETED/PARTIALLY_COMPLETED`

异常终态为 `FAILED`，用户取消为 `CANCELED`。上游 SQLite checkpointer 保存节点级断点，PostgreSQL 保存任务、事件与报告事实；Worker 重启后使用相同股票、日期和 Graph 形状恢复。失败任务可由用户重新入队，事件与产物使用唯一键保证重复恢复不产生重复事实。

## 数据准备

Worker 的股价事实只读取所选股票、指定时间范围内的 MiniQMT 本地未复权日线，不会静默切换行情源。财务、公告、新闻与宏观资料优先复用 AlphaDesk 已落库资料，并通过显式 AkShare 工具补充；外部工具失败会记录为 `DATA_UNAVAILABLE` 和失败事件，禁止模型编造。

情绪分析仍运行上游 TradingAgents 的真实情绪分析师节点，但其美股 StockTwits/Reddit 预取入口在 Worker 内被合法替换为 A 股公告与财经新闻，以及基于 MiniQMT 价格、成交量形成的可审计市场行为代理。报告不得声称读取未配置的海外社交平台；每项输入均保留 `source_id`。

## 部分成功

缺少任一必需角色报告时任务标为 `PARTIALLY_COMPLETED` 并列出缺口；Graph 整体失败、超时或无法恢复时标为 `FAILED`。系统不会用旧的逐角色摘要生成器静默代替真实 Graph。
