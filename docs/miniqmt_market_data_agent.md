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

历史补数队列采用“先查看、成功后确认”的可恢复语义。Agent 领取任务时不立即从 Redis
删除；只有全部 K 线已由 API 幂等写入 PostgreSQL 后才确认完成。进程崩溃或网络中断时，
队首任务仍会保留并在重启后继续。失败任务会移到队尾，避免单个异常证券阻塞全队列；连续
失败 3 次后进入死信队列供排查。等价请求使用稳定指纹持久去重，Agent 启动时还会压缩旧版
遗留的重复任务。由此重复点击、Worker 重启和多次扫描不会反复堆积相同下载批次。
每个批次完成或失败轮转后，队列还会按选股运行编号或批量回测关联编号切换到另一个业务任务；
大型全市场任务不能独占 Agent，后来提交的合法任务也会持续取得进展。修复前只记录单股回测
编号的旧任务按来源归组，确保旧积压也不会继续独占队列。
Docker 或 FastAPI 重启导致本地 HTTP 长连接失效时，Agent 会原地重建 API 客户端并持续退避
重试；它不会因此放弃当前未确认任务、重复创建请求或重新建立 MiniQMT 行情会话。API 恢复后
会从同一任务继续。

XtQuant 的同步历史下载由可中止超时保护，默认上限为 30 秒，可通过
`ALPHADESK_MINIQMT_HISTORY_DOWNLOAD_TIMEOUT_SECONDS` 调整。超时后 Agent 会请求 MiniQMT
终止当前下载并按失败协议轮转任务，避免一个异常分钟请求让智能选股或其他回测永久停在 0%。

历史补数优先于自动维护任务。自动维护、实时报价回调或单个无效快照失败只记录自身错误，
不得阻断历史队列。页面中的“正在下载”表示仍在等待或处理的股票；实际批次进度以已处理
批次数为准，不再把全部待处理股票误报为同时下载。

Agent 启动或断线重连后，会为当前自选、基准和临时查看范围自动补充最近 14 天日线及
最近 3 天 1 分钟线；交易日 15:10 后还会执行一次受限日线增量刷新。自动任务仍遵守
`ALPHADESK_MINIQMT_HISTORY_MAX_INSTRUMENTS`，不会订阅或下载全部 A 股。

## 故障定位

- “尚未配置”：检查 `ALPHADESK_MINIQMT_MARKET_DATA_ENABLED` 和数据目录。
- “MiniQMT行情服务尚未连接”：确认客户端已登录行情、XtQuant 路径正确，再运行
  `market-status` 或 `run-agent --once`。
- “订阅失败”：确认证券代码受当前 QMT 行情权限支持，并查看页面的中文最近错误。
- API 状态在线但没有行情：确认有基准标的、盘中监控自选股或 Scanner 结果，然后重新计算并同步。
- 历史补数长期无进度：先确认 Agent 心跳在线，再检查 Redis 的
  `alphadesk:miniqmt:v1:history:requests`（待处理）与
  `alphadesk:miniqmt:v1:history:dead-letter`（连续失败）长度。不要直接删除待处理队列；应重启
  Agent 触发队列压缩，或根据死信中的错误代码修复 MiniQMT 权限和数据问题后重新提交。

任何故障都不得通过启用交易 SDK、账户查询或真实订单来绕过。
