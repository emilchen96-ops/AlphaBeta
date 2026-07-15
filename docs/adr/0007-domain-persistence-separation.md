# ADR 0007：分离纯领域模型与持久化模型

- 状态：Accepted

## 背景

核心交易概念需要在 API、后台任务、测试和未来执行链路中保持一致，同时 SQLAlchemy 映射、连接和事务属于可替换的基础设施细节。若领域实体直接继承 ORM 基类，业务规则会被框架生命周期和数据库会话污染。

## 决策

核心实体、枚举、值校验、仓储协议和 Unit of Work 协议置于纯 Python 包 `alphadesk_domain`。SQLAlchemy 模型、实体映射、仓储实现及异步 Unit of Work 置于 `alphadesk_api.infrastructure`。仓储只 flush，由 Unit of Work 唯一控制 commit、rollback 和 session 生命周期。

## 原因

该边界使领域规则可在无 FastAPI、SQLAlchemy、Redis 和 Broker 的环境中测试，避免 ORM 对象泄漏到业务层，并保证多个事实可以在同一事务中提交。

## 后果

需要显式维护领域实体与持久化模型之间的映射，新增字段时必须同步更新实体、ORM、Migration、映射、测试和文档。应用层必须通过仓储协议和 Unit of Work 访问持久化能力。

## 被否决方案

以 SQLAlchemy Declarative Model 直接充当领域实体；在各仓储方法中独立提交事务；让领域层直接依赖 FastAPI 或具体数据库连接。
