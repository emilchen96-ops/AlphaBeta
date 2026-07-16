import { apiRequest } from "./client";
import type {
  AdjustmentType,
  InstrumentPage,
  MarketBarsResponse,
  MarketDataSource,
  MarketTimeframe,
  LatestQuotesResponse,
  RealtimeMarketStatus,
  Watchlist,
  WatchlistDetail,
  WatchlistItem,
} from "../types/market";

const jsonHeaders = { "Content-Type": "application/json" };

export function getInstruments(keyword: string) {
  const query = new URLSearchParams({ page: "1", page_size: "50" });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  return apiRequest<InstrumentPage>(`/api/v1/instruments?${query}`);
}

export function getLatestQuotes(instrumentIds: string[]) {
  const query = new URLSearchParams();
  for (const id of instrumentIds) query.append("instrument_ids", id);
  return apiRequest<LatestQuotesResponse>(
    `/api/v1/market-data/quotes/latest?${query}`,
  );
}

export function getRealtimeMarketStatus() {
  return apiRequest<RealtimeMarketStatus>(
    "/api/v1/market-data/realtime/status",
  );
}

export function getWatchlists() {
  return apiRequest<Watchlist[]>("/api/v1/watchlists");
}

export function getWatchlist(id: string) {
  return apiRequest<WatchlistDetail>(`/api/v1/watchlists/${id}`);
}

export function createWatchlist(name: string, description: string | null) {
  return apiRequest<Watchlist>("/api/v1/watchlists", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ name, description }),
  });
}

export function updateWatchlist(
  id: string,
  name: string,
  description: string | null,
) {
  return apiRequest<Watchlist>(`/api/v1/watchlists/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify({ name, description }),
  });
}

export function deleteWatchlist(id: string) {
  return apiRequest<void>(`/api/v1/watchlists/${id}`, { method: "DELETE" });
}

export function addWatchlistItem(watchlistId: string, instrumentId: string) {
  return apiRequest<WatchlistItem>(`/api/v1/watchlists/${watchlistId}/items`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ instrument_id: instrumentId, note: null }),
  });
}

export function updateWatchlistItem(
  watchlistId: string,
  itemId: string,
  note: string,
) {
  return apiRequest<WatchlistItem>(
    `/api/v1/watchlists/${watchlistId}/items/${itemId}`,
    {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ note: note || null }),
    },
  );
}

export function removeWatchlistItem(watchlistId: string, itemId: string) {
  return apiRequest<void>(`/api/v1/watchlists/${watchlistId}/items/${itemId}`, {
    method: "DELETE",
  });
}

export function reorderWatchlist(watchlistId: string, itemIds: string[]) {
  return apiRequest<void>(`/api/v1/watchlists/${watchlistId}/items/reorder`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ item_ids: itemIds }),
  });
}

export function getMarketSources() {
  return apiRequest<MarketDataSource[]>("/api/v1/market-data/sources");
}

export function getBars(
  instrumentId: string,
  timeframe: MarketTimeframe,
  adjustment: AdjustmentType,
) {
  const query = new URLSearchParams({
    instrument_id: instrumentId,
    timeframe,
    adjustment_type: adjustment,
    limit: "600",
  });
  return apiRequest<MarketBarsResponse>(`/api/v1/market-data/bars?${query}`);
}
