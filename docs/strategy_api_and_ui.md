# S01-C 策略研究 API 与页面

## 策略目录

`GET /api/v1/strategies/catalog` 和详情接口公开注册表中的稳定策略键、语义版本、支持周期及参数定义。目录不公开 Python 类名、源码路径或注册表实现。前端依据参数定义生成 integer、decimal、boolean、string 和 enum 控件；后端注册表仍是参数校验权威。

## 历史研究运行

`POST /api/v1/strategy-runs` 同步调用 S01-B StrategyRunner。客户端只提交策略键、参数、标的、周期、UTC 时间范围和幂等键；版本取当前注册版本，环境固定为 `RESEARCH`，Correlation ID 使用请求链路值。响应是真实终态或原幂等运行，不伪装排队任务。

运行列表和详情接口支持分页及策略、状态、标的和创建时间筛选。详情返回规范化参数、标的摘要、状态时间、脱敏错误、警告和只读能力边界。

## Signal 查询

`GET /api/v1/signals` 支持运行、策略、标的、类型和生成时间筛选；`GET /api/v1/strategy-runs/{run_id}/signals` 查询单次运行输出。价格、数量、权重和置信度以十进制字符串传输。接口只返回 DTO，不暴露 ORM 或 SQL 错误。

## 页面操作

- `/strategies`：查看目录和动态参数，选择标的与历史区间并同步启动研究运行。
- `/strategy-runs`：筛选、分页并查看运行状态；详情页显示参数、标的、状态时间和 Signal。
- `/signals`：筛选和查看研究 Signal、参考价格与原因。

提交期间按钮禁用以防重复点击；幂等键仍提供服务端最终保护。同步执行受 HTTP 请求时限约束，长任务、队列、Worker 和实时调度不属于 S01-C。

## 安全边界

Signal 是策略研究输出，不是 Order。S01-C 不创建 Order 或 Fill，不调用风控或 Broker，不改变现金、持仓或账本。`reference_price` 不是成交价；历史研究运行不提供手续费、滑点、收益曲线或绩效统计，也不是实时策略。
