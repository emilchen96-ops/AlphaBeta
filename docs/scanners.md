# SC01 A 股历史日线条件扫描器

SC01 提供统一的纯 Python Scanner 契约、两个内置规则、可审计的 PostgreSQL 运行事实，以及 API、CLI 和 React 页面。扫描只读取本地已有的 A 股日线，不抓取实时行情，不创建 Signal、RiskDecision、Order 或 Fill，也不修改账户、资金、持仓和账本。

## 安全边界

- ScanResult 只是规则匹配事实，不代表投资建议。
- 当前只支持 `DAY_1`、显式 Instrument 股票池和同步手工运行，不是实时全市场扫描。
- Scanner 不依赖 FastAPI、SQLAlchemy 或 Redis，不访问数据库，也不动态执行用户代码。
- 相同 K 线、参数、股票池和 `as_of` 产生确定性结果；当前 K 线不会进入历史均量。
- `limit_up_pullback` 使用可配置近似规则，不宣称完整复现交易所各板块涨停制度。

## 内置 Scanner

`volume_anomaly` 使用当前日线之前的 `volume_window` 根 K 线计算历史均量，以 `current_volume / average_volume` 作为主要评分，并支持成交额、价格和日收益率过滤。

`limit_up_pullback` 在回看窗口中寻找达到可配置收益率阈值的日线，以该日线前一交易日收盘价作为起涨基准，按当前价格距离、交易日间隔、是否高于基准和可选成交量确认筛选。

## 事实与幂等

Migration `0011_sc01` 新增：

- `scan_runs`：记录规范参数、股票池、截止时间、请求指纹、运行状态和统计；`idempotency_key` 唯一。
- `scan_results`：追加式结果事实；`(scan_run_id, instrument_id)` 与 `(scan_run_id, rank)` 唯一。

结果按 score 降序、Instrument UUID 升序稳定排名。相同幂等键和相同指纹返回原运行；相同键对应不同请求返回冲突。无匹配结果仍为 `COMPLETED`。

## API

```text
GET  /api/v1/scanners/catalog
POST /api/v1/scan-runs
GET  /api/v1/scan-runs
GET  /api/v1/scan-runs/{scan_run_id}
GET  /api/v1/scan-runs/{scan_run_id}/results
GET  /api/v1/scan-runs/{scan_run_id}/integrity
```

价格、评分和 Decimal 指标在 JSON 中使用十进制字符串，避免二进制浮点误差。错误响应遵循统一 error envelope 和 Correlation ID。

## CLI

从 `apps/api` 目录或 API 容器内运行：

```text
python -m alphadesk_api.cli.scanners run --scanner-key volume_anomaly --instrument-id <uuid> --as-of 2026-07-18T07:00:00+00:00 --idempotency-key demo-1 --param volume_window=20 --param minimum_volume_ratio=2
python -m alphadesk_api.cli.scanners list --scanner-key volume_anomaly
python -m alphadesk_api.cli.scanners show --scan-run-id <uuid>
python -m alphadesk_api.cli.scanners verify-integrity --scan-run-id <uuid>
```

## 网页

- `/scanners`：目录、参数定义、动态表单和 Instrument 多选股票池。
- `/scan-runs`：按扫描器和状态查询运行。
- `/scan-runs/{id}`：运行参数、统计、结果排名、规则原因和指标。

页面只提供到行情/Instrument、策略和研究 Signal 的只读导航，不提供买卖、转订单或自动交易动作。

## 验收

SC01 定向测试覆盖参数校验、数据不足、当前 K 线排除、成交量倍数、近似涨停、基准价、回落距离、稳定排序、幂等、结果唯一性、API、页面和交易/账本零副作用。迁移必须通过 upgrade、current、heads 和 check。
