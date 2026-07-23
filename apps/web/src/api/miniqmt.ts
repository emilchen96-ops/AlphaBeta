import { apiRequest } from "./client";
import type {
  MiniQMTStatus,
  RealtimeQuote,
  SubscriptionItem,
  SubscriptionPlan,
} from "../types/miniqmt";

type Envelope<T> = { schema_version: 1; data: T };

export async function getMiniQMTStatus() {
  return (
    await apiRequest<Envelope<MiniQMTStatus>>(
      "/api/v1/miniqmt/market-data/status",
    )
  ).data;
}

export async function getDesiredSubscriptions() {
  return (
    await apiRequest<Envelope<SubscriptionPlan>>(
      "/api/v1/market-subscriptions/desired",
    )
  ).data;
}

export async function getActiveSubscriptions() {
  return (
    await apiRequest<Envelope<{ items: SubscriptionItem[] }>>(
      "/api/v1/market-subscriptions/active",
    )
  ).data;
}

export async function getRealtimeQuotes() {
  return (
    await apiRequest<Envelope<{ items: RealtimeQuote[] }>>(
      "/api/v1/quotes?page=1&page_size=100",
    )
  ).data;
}

export async function rebuildSubscriptions() {
  return (
    await apiRequest<Envelope<SubscriptionPlan>>(
      "/api/v1/market-subscriptions/rebuild",
      { method: "POST" },
    )
  ).data;
}

export async function syncSubscriptions() {
  return (
    await apiRequest<Envelope<Record<string, unknown>>>(
      "/api/v1/market-subscriptions/sync",
      { method: "POST" },
    )
  ).data;
}

export function setTemporarySubscription(
  instrumentId: string,
  enabled: boolean,
) {
  return apiRequest<Envelope<{ enabled: boolean }>>(
    "/api/v1/market-subscriptions/temporary",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instrument_id: instrumentId, enabled }),
    },
  );
}
