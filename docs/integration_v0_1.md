# I01 V0.1 完整集成基线与 BT01-R 后续整合

> U01 更新：`/getting-started`、`alphadesk_api.cli.demo` 与 `/api/v1/demo/*` 已把当前
> 本地研究能力串成可重复的初始化/只读验收路径。系统能力接口现在额外报告汇总可用性、
> Provider、运行模式、最近成功时间和下一步操作；实时行情与 MiniQMT 的边界保持不变。

> 2026-07-20 后续状态：D01 与 BT01-R 已在 I01 基线上完成。当前回测 Migration 为 `0015_bt01`，唯一前驱为 `0014_d01`；日线回测 API、CLI、页面、绩效与 Integrity 均已接入。下文的 “I01 当时” 描述保留用于说明旧 BT01 为什么没有直接合并，不再代表当前能力状态。

## 基线与范围

- 来源分支/提交：`codex/scanner-information-ai` / `6d3aec6`。
- 集成分支：`codex/integration-v0.1`。
- 已整合：M01–M05、S01、S02、R01、B01、SC01、N01、A01。
- I01 当时只做盘点、只读能力检查、明确状态和确定性接线修复；D01 与 BT01-R 后来分别完成。RT01、真实 AI、Windows Agent、MiniQMT 与真实 Broker 仍未实施。

## BT01 审查结论

BT01 分支只有一个 `bfe72f8` 大提交，基于共同祖先 `4b4fee4`，跨 54 个文件、约 5,000 行，并新增 `0011_bt01`（down revision=`0010_b01`）。稳定分支已经使用 `0011_sc01 → 0012_n01 → 0013_a01`。

因此没有满足“边界清晰、无后续依赖、无多 head、不覆盖 SC01/N01/A01”的可安全 cherry-pick 提交。I01 当时没有整合 BT01。BT01-R 后来仅选择性复用领域、事件循环、API/CLI/UI 与测试思路，没有 merge 或 cherry-pick 旧大提交，也没有复用冲突的 `0011_bt01` Migration。

BT01-R 已把 Migration 重定位到 D01 后的唯一 head，并完成日线时钟、T+1 open、既有事实管道、费用与滑点、结果指标、幂等、API/CLI/UI、PostgreSQL 往返和浏览器验收。历史策略研究与资金回测仍是两个独立能力。

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

- Backtest：BT01-R 已完成；需要所选标的在 D01 本地库中具备足够权威日线。
- Audit、Settings：PLACEHOLDER；仅说明状态，无伪保存或查询动作。
- Realtime market：管道存在但 Provider disabled。
- MiniQMT/Windows Agent/真实 Broker：NOT_IMPLEMENTED。

## 可复现启动

全新数据库可直接升级到当前唯一 head `0015_bt01`：

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/capabilities
```

若旧数据卷仍停留在已删除的旧分支 revision `0011_bt01`，不要直接 stamp 或忽略错误。先核对旧回测表是否有数据并备份，再将其迁移到当前 `0014_d01 → 0015_bt01` 链；不确定时使用新的 Compose project/volume 建立干净基线：

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

D01 历史行情数据中心已在后续 `codex/d01-market-data` 分支完成。BT01-R 随后从该稳定基线选择性移植旧回测代码，并以新 Migration `0015_bt01` 接到 `0014_d01`，未合并旧 `0011_bt01`。日线回测现已接入 D01、S01/S02、R01、M05、B01 与 M04；分钟行情、分钟回测、MiniQMT 和真实交易仍未实现。下一阶段仅为 U01 一键初始化与系统可用性收口。
