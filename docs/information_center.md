# N01 资讯事件中心

N01 是 AI 分析之前的事实与来源层。它接收用户手工文本或 RSS/Atom 条目，保留不可覆盖的 RawDocument，生成规范化 InformationItem 和确定性 MarketEvent，并关联 Instrument 与主题。

## 边界

- 内容来自外部来源或用户输入，系统未验证所有事实真实性。
- N01 不使用 AI，不通过关键词冒充可靠方向判断；direction 由用户指定，默认 `UNKNOWN`。
- 内容不构成投资建议，不创建 Signal、RiskDecision、Order 或 Fill，不修改资金、持仓和账本。
- RSS 默认不轮询，不增加调度框架，不抓取条目链接中的网页全文，CI 只使用本地 XML Fixture。
- 不支持全网爬虫、登录站点、社交媒体、微信公众号自动抓取或付费内容破解。

## 事实模型

Migration `0012_n01` 新增：

- `information_sources`：MANUAL、RSS、ANNOUNCEMENT 或 OTHER 来源及非敏感配置。
- `information_ingestion_runs`：RSS 手工摄取的状态、计数、脱敏错误和 Correlation ID。
- `raw_documents`：原始标题、正文、来源 URL、外部 ID、发布时间、接收时间和 SHA-256。
- `information_items`：规范标题/正文、明确区分的发布时间和接收时间。
- `market_events`：事件类型、用户指定方向、可选 Decimal 重要度和 schema 版本。
- `event_instrument_links`、`event_theme_links`：事件与标的/主题的追加关联。

RawDocument 只验证原始文本非空，不裁剪或覆盖原文。显示、搜索与去重使用 Unicode NFKC、空白折叠后的规范内容。

## 去重

去重顺序为同一来源的 `external_id`，再检查全局规范内容 SHA-256。相同内容返回原 RawDocument、InformationItem 和 MarketEvent，不重复创建事件。URL 不是唯一键。

## API

```text
GET  /api/v1/information-sources
POST /api/v1/information/manual
POST /api/v1/information-sources/{source_id}/ingest
GET  /api/v1/information-items
GET  /api/v1/information-items/{item_id}
GET  /api/v1/market-events
GET  /api/v1/market-events/{event_id}
GET  /api/v1/information-items/{item_id}/integrity
```

列表支持来源、事件类型、方向、Instrument、主题和标题/正文搜索。importance 与 confidence 使用 Decimal/NUMERIC，API 使用十进制字符串，不接受浮点输入。

## CLI

```text
python -m alphadesk_api.cli.information add-manual --source-name "手工来源" --title "标题" --content "正文" --published-at 2026-07-18T01:00:00+00:00 --instrument-id <uuid> --theme bank=银行
python -m alphadesk_api.cli.information ingest-rss --source-name "RSS来源" --url https://example.test/feed.xml
python -m alphadesk_api.cli.information list --search 公告 --theme-key bank
python -m alphadesk_api.cli.information verify-integrity --item-id <uuid>
```

## 页面

- `/information`：来源/Instrument/主题/正文筛选、双时间展示和手工录入。
- `/information/{id}`：规范内容、原始内容、原始链接、关联与事件字段。
- `/market-events`：事件类型、方向和标题筛选。

所有页面持续展示外部事实、未验证、未经过 AI、非投资建议和不会创建订单的警告。
