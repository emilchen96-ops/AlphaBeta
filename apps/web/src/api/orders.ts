import { apiRequest } from "./client";
import type {
  CreateSimulatedExecutionRequest,
  ExecutionAttemptPage,
  ExecutionIntegrityReport,
  FillDetail,
  FillPage,
  OrderFactSummary,
  OrderPage,
  OrderTimelineItem,
  SimulatedExecutionResult,
} from "../types/orders";

const jsonHeaders = { "Content-Type": "application/json" };

export function getOrders(input: {
  page: number;
  pageSize: number;
  status?: string;
  accountId?: string;
  instrumentId?: string;
}) {
  const query = new URLSearchParams({
    page: String(input.page),
    page_size: String(input.pageSize),
  });
  if (input.status) query.set("status", input.status);
  if (input.accountId) query.set("account_id", input.accountId);
  if (input.instrumentId) query.set("instrument_id", input.instrumentId);
  return apiRequest<OrderPage>(`/api/v1/orders?${query}`);
}

export function getOrder(id: string) {
  return apiRequest<OrderFactSummary>(`/api/v1/orders/${id}`);
}

export function getOrderTimeline(id: string) {
  return apiRequest<OrderTimelineItem[]>(`/api/v1/orders/${id}/timeline`);
}

export function createOrder(input: {
  account_id: string;
  instrument_id: string;
  side: "BUY" | "SELL";
  order_type: "LIMIT" | "MARKET";
  time_in_force: string;
  requested_quantity: string;
  limit_price: string | null;
  expires_at: string | null;
  idempotency_key: string;
}) {
  return apiRequest<OrderFactSummary>("/api/v1/orders", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function confirmOrder(id: string, version: number, key: string) {
  return apiRequest<OrderFactSummary>(`/api/v1/orders/${id}/confirm`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      expected_order_version: version,
      idempotency_key: key,
    }),
  });
}

export function cancelOrder(id: string, version: number, key: string) {
  return apiRequest<OrderFactSummary>(`/api/v1/orders/${id}/cancel`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      expected_order_version: version,
      idempotency_key: key,
      reason: "用户从订单中心取消",
    }),
  });
}

export function executeSimulatedOrder(
  orderId: string,
  input: CreateSimulatedExecutionRequest,
) {
  return apiRequest<SimulatedExecutionResult>(
    `/api/v1/orders/${orderId}/simulated-executions`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
    15_000,
  );
}

export function getOrderExecutionAttempts(orderId: string) {
  return apiRequest<ExecutionAttemptPage>(
    `/api/v1/orders/${orderId}/execution-attempts?page=1&page_size=100`,
  );
}

export function getFills(input: {
  page: number;
  pageSize: number;
  accountId?: string;
  instrumentId?: string;
  orderId?: string;
  side?: string;
  executedFrom?: string;
  executedTo?: string;
}) {
  const query = new URLSearchParams({
    page: String(input.page),
    page_size: String(input.pageSize),
  });
  if (input.accountId) query.set("account_id", input.accountId);
  if (input.instrumentId) query.set("instrument_id", input.instrumentId);
  if (input.orderId) query.set("order_id", input.orderId);
  if (input.side) query.set("side", input.side);
  if (input.executedFrom) query.set("executed_from", input.executedFrom);
  if (input.executedTo) query.set("executed_to", input.executedTo);
  return apiRequest<FillPage>(`/api/v1/fills?${query}`);
}

export function getOrderFills(orderId: string) {
  return apiRequest<FillPage>(
    `/api/v1/orders/${orderId}/fills?page=1&page_size=100`,
  );
}

export function getFill(fillId: string) {
  return apiRequest<FillDetail>(`/api/v1/fills/${fillId}`);
}

export function getExecutionIntegrity(orderId: string) {
  return apiRequest<ExecutionIntegrityReport>(
    `/api/v1/orders/${orderId}/simulated-execution-integrity`,
  );
}
