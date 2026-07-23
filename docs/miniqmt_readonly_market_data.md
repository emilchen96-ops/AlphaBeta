# MiniQMT 只读行情

L2.5-A 将 MiniQMT 接入限定为行情数据源。它可提供实时快照、订阅/退订、历史日线和
历史 1 分钟线，但不会读取券商账户、资金、持仓、委托或成交，也没有下单、撤单和交易回调。

## 能力边界

- `MiniQMTMarketDataProvider` 只导入 `xtquant.xtdata`，不导入交易 SDK。
- Windows 行情代理固定报告 `market_data_capability=ENABLED` 和
  `trading_capability=DISABLED`。
- 订单类消息一律以 `MINIQMT_TRADING_DISABLED` 拒绝。
- Scanner、Strategy、React、Redis 和数据库代码均不直接依赖 XtQuant。
- “MiniQMT 已连接”只表示行情连接可用，不代表实盘交易可用。

## 数据链路

```text
盘中监控自选股 / 最新扫描结果 / 基准标的 / 临时查看标的
→ 期望订阅计划
→ Windows MiniQMT 行情代理
→ xtdata 实际订阅
→ QuoteSnapshot
→ Redis 最新快照 + WebSocket
→ D03 RAW 1分钟 MarketBar
→ Scanner / 行情页面 / 研究和后续回测
```

`QuoteSnapshot` 使用 `Decimal`，分别记录交易所行情时间、代理接收时间和后端摄取时间。
Redis 键为 `market:quote:{instrument_id}`，相同快照去重，旧行情不能覆盖新行情。Redis 是可恢复
的当前状态缓存，不是历史行情权威来源。研究和回测读取 PostgreSQL `market_bars`。

## 有限历史补数

`POST /api/v1/miniqmt/history/backfill` 只接受明确股票、时区日期范围和 `DAY_1` /
`MINUTE_1`，并受最大股票数和最大天数限制。API 只把请求放入有界队列；Windows 行情代理
分批下载并幂等写入 D01/D03 `MarketBar`。系统不会默认下载全市场多年分钟数据。

Agent 启动、重连及交易日收盘后还会对当前订阅范围执行小窗口幂等补数，用于修复短时断线
缺口；大范围、多年历史数据仍由数据中心按需发起。

## 页面与状态

MD01 已将原“实时行情”并入统一“行情”页面，并将原“分钟数据”并入“数据中心”。行情页
展示连接、订阅、实时快照和历史 K 线；数据中心展示目录、日线、分钟线、覆盖度和质量。
股票使用“名称（代码.市场）”，UUID、幂等键和 XtQuant 原始返回码不作为普通用户信息展示。
页面持续显示“交易能力：关闭（只读行情）”。

## 配置

从 `.env.example` 复制以下设置到未跟踪的 `.env`：

```text
ALPHADESK_MINIQMT_MARKET_DATA_ENABLED=true
ALPHADESK_MINIQMT_DATA_PATH=D:\QTM\DWZQ_QMT\userdata_mini
ALPHADESK_MINIQMT_XTQUANT_PATH=<包含 xtquant 包的本机目录，可留空>
ALPHADESK_MINIQMT_AGENT_API_URL=http://127.0.0.1:8000
ALPHADESK_MINIQMT_AGENT_TOKEN=<本机随机令牌>
```

数据路径和令牌不得由浏览器指定，也不会由状态 API 返回。
