import { apiRequest } from "./client";
import type {
  OrderFactSummary,
  OrderPage,
  OrderTimelineItem,
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
