# Windows MiniQMT 行情代理

Windows 行情代理必须运行在安装并登录 MiniQMT 的同一台 Windows 电脑上。API、PostgreSQL、
Redis 和 Web 可以继续使用 Docker；XtQuant 只存在于主机侧 Adapter/Agent 边界。

## 启动前提

1. 启动 MiniQMT 并登录“行情”入口，保持客户端运行。
2. 确认 `.env` 已启用只读行情并设置 MiniQMT 数据目录、XtQuant 路径、API URL 和代理令牌。
3. 在 Windows API 虚拟环境安装只读行情依赖：

```powershell
.\apps\api\.venv\Scripts\python.exe -m pip install -e ".\apps\api[miniqmt]"
```

4. 启动 AlphaDesk API，并执行最新 Migration。
5. 在仓库根目录、API Python 环境中启动代理：

```powershell
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt run-agent
```

日常使用可直接双击 `scripts/启动 AlphaDesk.cmd`：脚本会在 Docker、API 和前端就绪后
自动启动只读行情代理，并使用 `work/miniqmt-agent.pid` 避免重复进程。双击
`scripts/关闭 AlphaDesk.cmd` 会安全停止该代理。MiniQMT 未登录时不阻断离线研究功能，
但历史补数和实时行情会保持不可用状态。

一次诊断可使用 `run-agent --once`。常用只读命令：

```powershell
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt market-status
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt rebuild-subscriptions
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt sync-subscriptions
.\apps\api\.venv\Scripts\python.exe -m alphadesk_api.cli.miniqmt list-subscriptions
```

CLI 没有账户、资金、持仓、委托、成交、下单或撤单命令，也不会打印代理令牌。

## 运行行为

代理连接 `xtdata` 后定期读取期望计划、计算差异并调用 subscribe/unsubscribe。Tick 回调标准化
为 `QuoteSnapshot` 后批量发送给 API；1 分钟回调按交易所行情时间归一为 Bar 开始时间，再由
D03 会话规则校验并幂等写库。前端断线不影响代理、Redis 或分钟 Bar 入库。

代理对队列设置上限，API/Redis 暂时不可用时不会无限占用内存。API 使用带过期时间的 Agent
心跳区分在线与离线；页面 WebSocket 使用指数退避重新连接。历史缺口通过行情页或数据中心
提交受限补数任务，MiniQMT 和 Agent 必须保持运行。

SC01-R 全市场扫描也复用同一历史补数队列。Scanner Worker 先在数据库检查每只股票的
最低日线数量，只把缺失股票按最多 50 只一批提交给 Agent；它不会在 FastAPI 进程中加载
XtQuant，也不会建立全市场实时订阅。Agent 处理补数后，Scanner Worker 以数据库中的
MiniQMT 日线为准重新检查并继续扫描。

Agent 启动或断线重连后，会为当前自选、基准和临时查看范围自动补充最近 14 天日线及
最近 3 天 1 分钟线；交易日 15:10 后还会执行一次受限日线增量刷新。自动任务仍遵守
`ALPHADESK_MINIQMT_HISTORY_MAX_INSTRUMENTS`，不会订阅或下载全部 A 股。

## 故障定位

- “尚未配置”：检查 `ALPHADESK_MINIQMT_MARKET_DATA_ENABLED` 和数据目录。
- “MiniQMT行情服务尚未连接”：确认客户端已登录行情、XtQuant 路径正确，再运行
  `market-status` 或 `run-agent --once`。
- “订阅失败”：确认证券代码受当前 QMT 行情权限支持，并查看页面的中文最近错误。
- API 状态在线但没有行情：确认有基准标的、盘中监控自选股或 Scanner 结果，然后重新计算并同步。

任何故障都不得通过启用交易 SDK、账户查询或真实订单来绕过。
