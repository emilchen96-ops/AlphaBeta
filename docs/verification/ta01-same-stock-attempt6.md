# TA01 同股逐项验收

- AlphaDesk 任务：`0ea29f0a-d695-455e-b9ac-c04f590e07c3`
- 股票：`300115`
- 状态：`COMPLETED`
- Graph：`tradingagents_graph` / `a33fd4c0f134485a43553a2c23a63cb14adbd88f`
- 角色覆盖：12/12 (100.0%)；上游基准 12/12
- 工具调用：成功 29，失败 0
- 来源覆盖：100.0%

## 独立报告

| 角色 | 上游 | AlphaDesk | 上游字符 | AlphaDesk字符 | AlphaDesk引用数 |
|---|---:|---:|---:|---:|---:|
| MARKET_ANALYST | 是 | 是 | 3734 | 6752 | 0 |
| SENTIMENT_ANALYST | 是 | 是 | 1208 | 4706 | 3 |
| NEWS_ANALYST | 是 | 是 | 2895 | 6620 | 0 |
| FUNDAMENTAL_ANALYST | 是 | 是 | 6547 | 5560 | 0 |
| BULL_RESEARCHER | 是 | 是 | 7438 | 2487 | 0 |
| BEAR_RESEARCHER | 是 | 是 | 8588 | 2697 | 0 |
| RESEARCH_MANAGER | 是 | 是 | 1980 | 2421 | 0 |
| TRADER | 是 | 是 | 1261 | 1560 | 0 |
| AGGRESSIVE_RISK_ANALYST | 是 | 是 | 5208 | 1436 | 0 |
| NEUTRAL_RISK_ANALYST | 是 | 是 | 4457 | 1769 | 0 |
| CONSERVATIVE_RISK_ANALYST | 是 | 是 | 4261 | 1295 | 0 |
| PORTFOLIO_MANAGER | 是 | 是 | 1905 | 2655 | 0 |

## 来源类型

- A股市场情绪：1 个来源引用
- MiniQMT行情：254 个来源引用
- 公司公告：1 个来源引用
- 宏观：9 个来源引用
- 新闻：2 个来源引用
- 财务报表：4 个来源引用
