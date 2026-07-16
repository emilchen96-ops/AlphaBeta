import { apiRequest } from "./client";
import type {
  Account,
  AccountSnapshot,
  AccountSummary,
  AccountLiveValuation,
  CashLedgerEntry,
  LedgerTransaction,
  Page,
  PositionLedgerEntry,
  Reconciliation,
} from "../types/accounting";

const jsonHeaders = { "Content-Type": "application/json" };

export function getAccounts() {
  return apiRequest<Page<Account>>("/api/v1/accounts?page=1&page_size=100");
}

export function createAccount(input: {
  account_code: string;
  name: string;
  initial_cash: string;
  settlement_policy: "IMMEDIATE" | "T_PLUS_ONE";
  idempotency_key: string;
}) {
  return apiRequest<Account>("/api/v1/accounts", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ ...input, base_currency: "CNY" }),
  });
}

export function getAccountSummary(id: string) {
  return apiRequest<AccountSummary>(`/api/v1/accounts/${id}/summary`);
}

export function getAccountLiveSummary(id: string) {
  return apiRequest<AccountLiveValuation>(
    `/api/v1/accounts/${id}/live-summary`,
  );
}

export function postFunding(
  id: string,
  kind: "deposits" | "withdrawals",
  amount: string,
  idempotencyKey: string,
) {
  return apiRequest<LedgerTransaction>(`/api/v1/accounts/${id}/${kind}`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ amount, idempotency_key: idempotencyKey }),
  });
}

export function valueAccount(id: string) {
  return apiRequest<AccountSnapshot>(
    `/api/v1/accounts/${id}/valuation-snapshots`,
    { method: "POST" },
  );
}

export function reconcileAccount(id: string) {
  return apiRequest<Reconciliation>(`/api/v1/accounts/${id}/reconciliations`, {
    method: "POST",
  });
}

export function getCashLedger(id: string) {
  return apiRequest<Page<CashLedgerEntry>>(
    `/api/v1/accounts/${id}/cash-ledger?page=1&page_size=100`,
  );
}

export function getPositionLedger(id: string) {
  return apiRequest<Page<PositionLedgerEntry>>(
    `/api/v1/accounts/${id}/position-ledger?page=1&page_size=100`,
  );
}

export function getSnapshots(id: string) {
  return apiRequest<Page<AccountSnapshot>>(
    `/api/v1/accounts/${id}/valuation-snapshots?page=1&page_size=100`,
  );
}

export function getReconciliations(id: string) {
  return apiRequest<Page<Reconciliation>>(
    `/api/v1/accounts/${id}/reconciliations?page=1&page_size=100`,
  );
}
