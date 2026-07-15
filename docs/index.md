# AlphaDesk 文档索引

当前里程碑：**M01 已完成**。系统具备本地基础设施和空管理后台，不具备量化交易业务、认证或实盘能力。

## 阅读顺序

1. [架构总览](architecture.md)：系统边界、依赖方向与两条交易链路。
2. [开发路线图](development_roadmap.md)：M00–M14 的交付顺序和验收门槛。
3. [领域模型](domain_model.md) 与 [事件模型](event_model.md)：统一语言、事实与审计基础。
4. [订单状态机](order_state_machine.md)、[可靠消息](reliable_messaging.md) 与 [风险模型](risk_model.md)：下单安全闭环。
5. [回测规则](backtest_rules.md)、[安全规范](security.md)、[测试策略](testing_strategy.md) 与 [编码标准](coding_standards.md)。
6. [架构决策记录](adr/index.md)：了解不可随意改变的架构选择。

## 按任务定位

| 变更内容 | 必读文档 |
| --- | --- |
| 策略、信号、回测 | `domain_model.md`、`backtest_rules.md`、`risk_model.md` |
| 订单、成交、执行器 | `order_state_machine.md`、`reliable_messaging.md`、`risk_model.md`、`security.md` |
| 数据库、事件、审计 | `event_model.md`、`reliable_messaging.md`、ADR 0002、0004 |
| Redis、队列、推送 | `reliable_messaging.md`、ADR 0003、0004 |
| Web 或 API | `architecture.md`、`security.md`、`coding_standards.md` |
| Broker 或行情适配器 | `architecture.md`、`risk_model.md`、ADR 0005 |

若文档与实现发生冲突，先暂停变更并更新经评审的文档或 ADR；不得以临时实现绕过既定约束。

## M01 实现入口

- 本地启动和验收：根目录 `README.md`、`compose.yaml` 与 `scripts/`。
- FastAPI：`apps/api/src/alphadesk_api/`，依赖锁在 `apps/api/requirements.lock`。
- React：`apps/web/src/`，依赖锁在 `apps/web/package-lock.json`。
- CI：`.github/workflows/ci.yml`。

M01 的数据库迁移仅维护 Alembic 版本，不创建任何交易领域表；Redis 仅做连接检查，未建立 Streams 或业务缓存。
