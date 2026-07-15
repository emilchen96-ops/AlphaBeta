# 账户账本核对

核对服务从只追加账本独立重算现金总额和各标的总数量，再与当前 `account_cash_balances`、`positions` 投影比较。它不依赖网页缓存或 Redis。

现金按币种汇总所有 `CashLedgerEntry.total_delta`；持仓按标的汇总所有 `PositionLedgerEntry.quantity_delta`。结果追加到 `account_reconciliation_runs`：

- `MATCHED`：账本重算值与投影一致，差异数为零。
- `MISMATCHED`：至少一项不一致，输出种类、键、期望值和实际值。
- `FAILED`：为未来不可完成的核对故障预留；故障必须审计，不得伪装为一致。

单次记录最多保存 100 条差异，防止无界元数据。M04 默认只报告、不自动修复；修复投影或追加反向分录必须是后续经审查的显式操作。
