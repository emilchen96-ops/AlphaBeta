# I01 V0.1 完整集成基线

## 基线与范围

- 来源分支/提交：`codex/scanner-information-ai` / `6d3aec6`。
- 集成分支：`codex/integration-v0.1`。
- 已整合：M01–M05、S01、S02、R01、B01、SC01、N01、A01。
- I01 只做盘点、只读能力检查、明确状态和确定性接线修复；没有实施 D01、BT01-R、RT01、真实 AI、Windows Agent、MiniQMT 或真实 Broker。

## BT01 审查结论

BT01 分支只有一个 `bfe72f8` 大提交，基于共同祖先 `4b4fee4`，跨 54 个文件、约 5,000 行，并新增 `0011_bt01`（down revision=`0010_b01`）。稳定分支已经使用 `0011_sc01 → 0012_n01 → 0013_a01`。

因此没有满足“边界清晰、无后续依赖、无多 head、不覆盖 SC01/N01/A01”的可安全 cherry-pick 提交。I01 不整合 BT01；独立分支和本机已有 BT01 数据均被保留，回测状态为 PARTIAL。

BT01-R 至少需要：把回测 Migration 重定位到当前唯一 head 之后；重放与 SC01/N01/A01 的共享代码差异；证明日线时钟、事件循环、费用、滑点、涨跌停/T+1、结果指标和幂等；完成 API/CLI/UI、真实 PostgreSQL、Migration 往返和浏览器专项验收；不得把历史策略研究误称收益回测。

## 当前可直接使用

- 系统健康、状态、WebSocket 展示连接与只读 capability 检查。
- N01 手工资讯录入、资讯/事件查询和详情。
- A01 既有运行/Evidence 查询；显式 Fake Provider 下可做确定性本地研究验收。
- 策略、扫描器目录、R01 当前限制和各类空状态查询。
- 创建模拟账户本身不依赖行情；后续资金/订单动作仍需要对应事实。

## 数据或配置满足后可用

- Instrument/MarketBar 后：行情、自选股、Scanner、Strategy、Signal、StrategyExperiment。
- 模拟账户 + Instrument 后：Order、RiskDecision；人工确认后：Simulated Broker、Fill 和账本闭环。
- Provider 显式启用且有 Evidence 后：AI Research。当前只支持 Fake 验收，真实 AI 不可用。

## 占位与未实现

- Backtest：PARTIAL，当前分支无运行 API/按钮。
- Audit、Settings：PLACEHOLDER；仅说明状态，无伪保存或查询动作。
- Realtime market：管道存在但 Provider disabled。
- MiniQMT/Windows Agent/真实 Broker：NOT_IMPLEMENTED。

## 可复现启动

全新或 Alembic 为 `0013_a01` 的数据库：

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/capabilities
```

若本机默认 `alphadesk` 数据卷曾在 BT01 分支升级到 `0011_bt01`，不要删除或强制降级。保留旧项目后，用新的 Compose project/volume 建立干净基线（执行前先停止占用 5173/8000 的旧容器）：

```powershell
docker compose down
docker compose -p alphadesk-i01 up --build -d
docker compose -p alphadesk-i01 exec api alembic current
docker compose -p alphadesk-i01 exec api alembic heads
docker compose -p alphadesk-i01 exec api alembic check
```

验收地址：Web `http://127.0.0.1:5173`，API `http://127.0.0.1:8000`，OpenAPI `http://127.0.0.1:8000/docs`。

## I01 修复

- 新增服务端权威只读 `/system/capabilities`，聚合实现、数据、配置和必要动作。
- 首页显示能力矩阵。
- AI Provider 未配置时禁用创建按钮；订单、策略、批量实验和扫描器在前置数据缺失时禁用写操作并显示原因。
- Backtest/Audit/Settings 页面及导航准确标记 PARTIAL/计划/只读，移除任何虚假可用暗示。
- 修复模拟成交时间晚于记账进程时 `posted_at` 早于 `occurred_at` 的边界，并校正跨模块集成测试的数据隔离与已存在只读路径的 405 契约断言。
- 保留 localhost/127.0.0.1 双回环 CORS。

## 下一阶段

D01 历史行情数据中心：Instrument 同步、增量日线补数、幂等、覆盖率、交易日历、复权/质量状态、缺口检测、可恢复同步和数据就绪 API。D01 不应包含回测撮合或实盘执行。
