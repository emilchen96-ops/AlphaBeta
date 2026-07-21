# I01 页面与按钮盘点

> U01 新增“开始使用”“一键创建演示研究环境”和“只读验收”。初始化按钮只在开发/测试
> 环境调用 `/api/v1/demo/initialize-research`；失败会显示可操作错误，不静默吞掉。

状态沿用 I01 枚举。表中“条件显示”表示按钮由后端返回的 capability/status 控制，不是前端绕过后端规则。

| 页面 | 按钮文案 | 点击事件 | API 调用 | 成功行为 | 失败行为 | 所需数据/配置 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 全局 | 折叠导航 | 切换侧栏状态 | 无 | 收起/展开导航 | 不适用 | 无 | WORKING |
| 首页 | 刷新状态 | `refresh` | `GET /system/status` | 更新基础设施卡片 | 显示错误 Alert 和重连 | API | WORKING |
| 首页 | 重新连接 | `refresh` | `GET /system/status` | 恢复状态展示 | 保留错误 Alert | API | WORKING |
| 行情 | 刷新 K 线 | `bars.refetch` | `GET /market-data/bars` | 更新图表/空状态 | 通用错误提示 | Instrument/MarketBar | NEEDS_DATA |
| 行情 | 新建/编辑/删除自选股 | 对话框 + mutation | `POST/PATCH/DELETE /watchlists*` | 刷新自选股 | 消息提示 | PostgreSQL | WORKING |
| 行情 | 上移/下移/移除标的 | mutation | `POST .../reorder`、`PATCH/DELETE .../items*` | 刷新顺序 | 消息提示 | WatchlistItem | NEEDS_DATA |
| 行情 | 添加到自选股 | mutation | `POST /watchlists/{id}/items` | 刷新自选股 | 消息提示 | Instrument/Watchlist | NEEDS_DATA |
| Portfolio | 新建模拟账户 | 打开表单并提交 | `POST /accounts` | 创建并刷新 | message.error | 本地数据库 | WORKING |
| Portfolio | 入金/出金 | 打开表单并提交 | `POST /accounts/{id}/deposits|withdrawals` | 写账本并刷新 | message.error | 模拟账户 | NEEDS_DATA |
| Portfolio | 重新估值 | mutation | `POST /accounts/{id}/valuation-snapshots` | 新增快照 | 显示失败 | 账户、持仓、行情 | NEEDS_DATA |
| Portfolio | 执行核对 | mutation | `POST /accounts/{id}/reconciliations` | 新增核对事实 | 显示失败 | 模拟账户 | NEEDS_DATA |
| Portfolio | 刷新 | invalidate queries | 多个 GET | 更新投影 | 查询错误 Alert | 模拟账户 | NEEDS_DATA |
| Orders | 创建订单 | 打开表单并提交 | `POST /orders` | 展示 R01 结果/订单 | REJECT/REVIEW 有明确 Decision 链接 | 账户、Instrument | NEEDS_DATA |
| Orders | 详情 | 选择行 | `GET /orders/{id}` 及关联查询 | 打开 Drawer | 查询错误 | Order | NEEDS_DATA |
| Orders | 人工确认 | 二次确认 | `POST /orders/{id}/confirm` | 状态进入 QUEUED | 冲突/错误提示 | WAITING_CONFIRMATION | NEEDS_DATA |
| Orders | 取消 | mutation | `POST /orders/{id}/cancel` | 状态更新 | 版本冲突提示 | 可取消 Order | NEEDS_DATA |
| Orders | 模拟执行 | 打开显式市场快照对话框 | `POST /orders/{id}/simulated-executions` | Attempt/Fill/账本刷新 | 受控拒绝或错误提示 | 可执行 Order | NEEDS_DATA |
| Fills | 查看详情 | 选择 Fill | `GET /fills/{id}` | 展示费用和现金影响 | 查询错误 | Fill | NEEDS_DATA |
| Risk | 查看详情 | 路由跳转 | `GET /risk-decisions/{id}` | 展示规则事实 | 错误 Alert | RiskDecision | NEEDS_DATA |
| Signals | 查看/风险评估 | 打开 Modal 并提交 | `POST /signals/{id}/risk-assessments` | 展示独立 Decision | 错误提示 | Signal、账户 | NEEDS_DATA |
| Strategies | 批量研究 | 路由跳转 | 无立即写入 | 打开参数网格 | 不适用 | 策略目录 | WORKING |
| Strategies | 创建研究运行 | 展开表单 | 无立即写入 | 显示动态参数 | 不适用 | Instrument | NEEDS_DATA |
| Strategies | 运行历史研究 | 提交表单 | `POST /strategy-runs` | 跳转运行详情 | message.error | 历史 K 线 | NEEDS_DATA |
| Strategy Runs | 查看详情/Signal | 路由跳转 | `GET /strategy-runs/{id}`、`GET /signals` | 展示事实 | 查询错误 | StrategyRun | NEEDS_DATA |
| Strategy Experiments | 开始批量研究 | 提交参数网格 | `POST /strategy-experiments` | 跳转详情 | 显示 ErrorNotice/Correlation ID | 历史 K 线 | NEEDS_DATA |
| Scanner | 查看扫描运行/行情/策略/Signal | 路由跳转 | 无立即写入 | 打开目标页 | 不适用 | 无 | WORKING |
| Scanner | 创建扫描运行 | 展开表单 | 无立即写入 | 显示参数 | 不适用 | Instrument | NEEDS_DATA |
| Scanner | 运行历史日线扫描 | 提交表单 | `POST /scan-runs` | 跳转结果详情 | message.error | 足够历史日线 | NEEDS_DATA |
| Scan Runs | 新建扫描/查看详情 | 路由跳转 | 对应 GET | 打开页面 | 查询错误 | ScanRun | NEEDS_DATA |
| Information | 录入手工资讯 | 切换表单 | 无立即写入 | 显示表单 | 不适用 | 无 | WORKING |
| Information | 保存资讯 | 提交表单 | `POST /information/manual` | 跳转详情并刷新 | message.error | 标题、正文、来源 | WORKING |
| Information | 市场事件/资讯中心/查看原始事实 | 路由跳转 | 对应 GET | 打开列表/详情 | 查询错误 | InformationItem | WORKING |
| AI Research | 创建研究分析 | 提交表单 | `POST /ai/analyses` | 跳转运行详情 | message.error | Evidence + Provider | NEEDS_CONFIG |
| AI Research | 查看依据/Insight 目录/证据详情 | 路由跳转 | 对应 GET | 展示只读证据 | 查询错误 | 已有运行 | WORKING |
| Backtest | 创建回测/重新生成幂等键/查看详情 | 同步提交并路由到结果 | `POST /backtests` 与各结果 GET | 展示状态、指标、曲线、交易事实、Timeline 和 Integrity | 显示后端权威错误与 Correlation ID | D01 本地日线 | NEEDS_DATA |
| Historical Replay | 创建/查看 | 提交配置并路由详情 | `POST /replays` 与结果 GET | 建立独立账户和 READY Run | 数据/配置错误与 Correlation ID | D01 本地日线 | NEEDS_DATA |
| Historical Replay | 启动/暂停/恢复/单步/倍速/停止 | 状态化 mutation | `POST /replays/{id}/start|pause|resume|step|speed|stop` | 更新版本、游标、事实与 Timeline | 幂等、版本、终态、Worker 错误明确展示 | READY/RUNNING/PAUSED | WORKING |
| Audit | 无查询/导出按钮 | 无 | 无 | 显示计划状态 | 不适用 | 统一审计 API 未实现 | PLACEHOLDER |
| Settings | 无保存/应用按钮 | 无 | 无 | 显示只读说明 | 不适用 | 设置写 API 未实现 | PLACEHOLDER |

## 静态事件处理检查

- `TODO`、`FIXME`、仅 `console.log`、空 `onClick`：在 `apps/web/src` 与 `apps/api/src` 未发现。
- 前端导航目标均存在于 `router.tsx`；条件动作根据后端状态显示。
- AI Provider 为 disabled 时提交按钮现已禁用；订单、策略、批量实验和扫描器在 capability 明确报告前置数据缺失时禁用创建/运行按钮并展示原因；Backtest 与 Historical Replay 提供本地历史运行入口，Audit 与 Settings 仍不暗示存在未实现动作。
- 加载与失败：主要写操作均使用 React Query mutation 的 loading/error；列表使用 Table/Alert/Empty。个别只读导航无需网络加载状态。
