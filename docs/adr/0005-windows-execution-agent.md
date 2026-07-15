# ADR 0005：Windows 本地执行器作为交易安全边界

- 状态：Accepted

## 背景

MiniQMT/XtQuant 及券商账户运行在本地 Windows 环境。浏览器与后端不应直接拥有调用券商的能力。

## 决策

部署独立的 Python Windows 本地交易执行器，通过受认证的可靠命令队列接收请求，并经 Broker Adapter 调用模拟 Broker 或未来的 MiniQMT/XtQuant。执行器可独立拒绝命令。

## 原因

缩小真实交易权限的暴露面，适配 Windows 生态，并把最后一次安全校验放在最接近 Broker 的位置。

## 后果

必须实现设备身份、签名、恢复、对账和运维监控；后端不能把执行器视为永远在线的同步服务。

## 被否决方案

从 Web 浏览器直接调用券商；由 FastAPI 进程直接持有并调用本地交易 SDK。
