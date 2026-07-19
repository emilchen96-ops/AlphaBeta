# D01-E 历史行情数据中心页面

入口为 `/market-data-center`，复用 AlphaDesk 现有布局、Ant Design 表格/状态标签、统一 API 客户端和错误处理。

页面包含五区：

1. 数据总览：A 股/研究池/日线数量、覆盖日期、Provider、Scanner/Strategy/BT01 状态；
2. Universe 覆盖：有数据、充足、不足数量，以及不足标的的 Mapping 和缺失要求；
3. 同步运行：受限 dry-run/实际更新表单和 `MarketSyncRun` 统计；
4. 数据质量：创建运行、历史运行、Issue 和筛选；
5. 功能可用性：各 Scanner、Strategy 与日线回测的后端 Readiness 和合理跳转。

页面明确说明操作只维护历史日线、不提供实时行情、不连接 MiniQMT。第一版同步请求没有伪进度或 QUEUED 状态，执行时禁用重复提交；部分失败以警告展示真实失败数。页面没有 MarketBar 编辑、删除、补零按钮，也不会自动创建 Signal、订单、成交或回测。
