# RT01 回放页面

入口 `/replays` 提供运行列表与创建表单，详情 `/replays/:replayId` 提供控制台。按钮由后端状态
决定是否可用；重复点击通过动作幂等键和行版本保护，不会重复推进。

详情展示：当前 Session 与历史 K 线、现金/权益/仓位、权益曲线和回撤、Signal、RiskDecision、
Order、Fill、追加式 Timeline、最终绩效及 Integrity。页面通过 WebSocket 接收事件通知，并以
定时查询为恢复路径，因此断线重连不会把 Redis 当成事实源。

页面顶部永久显示边界：历史回放不是实时行情，不连接 MiniQMT/券商，不会产生真实交易，速度
不等于真实市场速度，当前不支持分钟或 Tick 回放。
