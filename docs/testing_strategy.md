# 测试策略

> M04.1A 默认测试使用 fake provider，覆盖字符串到 Decimal、缺失上游时间、时区、限流熔断、Redis revision/去重/乱序和 leader ownership。默认 CI 不访问外部网络；只有 `ALPHADESK_EXTERNAL_FREE_MARKET_TESTS=true` 时运行 `tests/external`。

> M04 测试覆盖 Decimal 公式、幂等、资金/持仓不足、PostgreSQL 迁移与约束、成交闭环、估值状态、核对和 `/portfolio` 前端；并发测试必须使用真实 PostgreSQL 行锁。

## M03 行情验收基线

- 单元测试覆盖行情实体数值/UTC/周期校验、确定性 DEMO、禁用外部入口和 CSV 文件边界。
- PostgreSQL 集成测试覆盖 0003 upgrade、downgrade 到 0002、re-upgrade、批量 Upsert 幂等计数、同步事件/审计且无 Outbox 发布。
- API 测试覆盖标的、自选股、K 线、来源、同步记录与统一错误信封；前端测试覆盖 API 契约、空/加载/K 线状态和行情路由交互。
- 前端测试环境兼容 Ant Design 的伪元素探测并显式等待异步 React 更新；完整 Vitest 输出不包含 `act(...)` 或 jsdom 伪元素警告。
- 生产构建通过 Rolldown 将 React、Ant Design 和其他依赖分组切包；当前最大压缩前 JavaScript 分包约 225 kB，低于 500 kB 告警阈值。
- `seed-demo` 必须连续运行两次：首次新增，第二次新增和更新均为零。
- 本地入口为 `scripts/check_m03.ps1` 或 `scripts/check_m03.sh`；集成测试只允许连接数据库名包含 `test` 的显式测试 URL。

测试是未来每项功能变更的必需交付物。不得以删除功能、跳过关键场景或伪造通过结果来替代测试。

| 类型 | 目标 | 重点场景 |
| --- | --- | --- |
| 单元测试 | 验证领域规则的确定性行为 | 信号、风控规则、状态迁移、费用计算 |
| API 测试 | 验证授权、输入、响应与错误契约 | 身份、参数校验、只读与受控操作 |
| 数据库集成测试 | 验证事务、Migration 和持久化约束 | 订单与 Outbox 同事务、审计不可缺失 |
| 状态机测试 | 覆盖合法和非法订单迁移 | 终态保护、取消竞态、对账暂停 |
| 合约测试 | 验证模块、Adapter 与消息契约 | schema 版本、Broker/行情接口、回执格式 |
| 幂等测试 | 验证重复输入不重复产生经济效果 | 重复命令、重复回执、重复成交 |
| 断网恢复测试 | 验证队列、执行器和回执恢复 | Pending 认领、重启、消息重放 |
| 风控测试 | 验证任一拒绝均不可下单 | 限额、白黑名单、只卖、急停、行情过期 |
| 回测确定性测试 | 验证统一接口与可重现结果 | 固定数据/参数/种子、无未来数据泄漏 |
| 执行器恢复测试 | 验证本地故障后的安全状态 | 重启、设备吊销、命令过期、Broker 不确定性 |

对订单、资金、权限、消息和对账相关变更，应优先增加集成与故障测试，而不仅是单元测试。测试应使用隔离的模拟数据和模拟 Broker；不得使用真实账户或密钥。

## M01 测试基线

- 后端单元测试覆盖存活/就绪、依赖故障、系统状态脱敏、Correlation ID、错误信封、WebSocket ping/pong、环境配置与客户端替换。
- 后端集成测试通过显式 `ALPHADESK_RUN_INTEGRATION=true` 启用，避免普通单元测试依赖开发者本机服务。
- 前端测试覆盖布局、导航、Dashboard 加载/成功/失败、服务状态、404 与 WebSocket Hook 清理。
- CI 使用隔离的 PostgreSQL 和 Redis Service Container；本地 Docker 脚本运行与 CI 相同的质量命令。
- 每次交付必须区分“通过”“跳过”和“环境不可运行”，不得把未执行的 Docker 或集成验收写成通过。

## M01.1 已执行验收基线

- Docker Compose 四服务构建和健康检查通过，PostgreSQL 与 Redis 使用真实容器而非 Mock。
- API 容器内 `ruff check .`、`ruff format --check .`、`mypy src` 通过；Pytest 共 16 项通过，其中 1 项真实依赖集成测试已执行且没有跳过。
- Web 的 ESLint、TypeScript、Vitest 和生产构建通过；M01 时的主包大于 500 kB 警告已在 M03 通过页面懒加载与供应商分组切包解决。
- 浏览器验证覆盖首页状态、手动刷新、路由切换、深链接刷新、WebSocket 与控制台；最终控制台错误数为 0。
- PostgreSQL 或 Redis 离线时，存活检查保持 200、就绪检查返回 503，页面显示对应依赖离线；恢复服务后重新就绪。
- API 离线时 Web 仍可访问并显示 API 离线、WebSocket 断开；API 恢复后连接自动恢复，未出现控制台错误洪泛。
- 整组 `docker compose restart` 后，Alembic 版本与 Redis 持久性探针均保留，且两个命名卷未被删除。

## M02 数据库验收基线

- 纯领域单元测试覆盖 Decimal/UTC 校验、非法值拒绝、框架依赖隔离、append-only 协议和 UoW commit/rollback/close 行为。
- PostgreSQL 集成测试只使用独立 `alphadesk_test` 数据库；先执行 upgrade，再 downgrade 到 M01、重新 upgrade 到 head，并执行 `alembic check`。
- 数据库测试直接验证业务唯一键、复合唯一键、部分唯一索引、数量/价格/有效期检查和事件/命令/成交/Outbox 幂等约束。
- 仓储测试验证实体映射、业务键查询、Decimal 与 UTC 往返；事务测试验证 Order、Transition、Event、Audit、Outbox 同时提交、强制失败整体回滚，以及回滚后新事务可恢复。
- 本地入口为 `scripts/check_m02.ps1` 或 `scripts/check_m02.sh`；CI 使用同名隔离数据库并显式开启 M02 集成测试。
