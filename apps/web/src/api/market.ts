import { apiRequest } from "./client";
import type {
  AdjustmentType,
  InstrumentPage,
  Instrument,
  MarketBarsResponse,
  MarketDataSource,
  MarketTimeframe,
  LatestQuotesResponse,
  RealtimeMarketStatus,
  DailyUpdateResult,
  MarketDataOverview,
  MarketSyncRun,
  MarketReferenceStatus,
  QualityRunDetail,
  QualityRunPage,
  ReadinessCapability,
  ReferenceSyncResult,
  UniverseCoverage,
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

export function getInstrument(id: string) {
  return apiRequest<Instrument>(`/api/v1/instruments/${id}`);
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

export function createWatchlist(
  name: string,
  description: string | null,
  realtimeEnabled = false,
) {
  return apiRequest<Watchlist>("/api/v1/watchlists", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      name,
      description,
      realtime_enabled: realtimeEnabled,
    }),
  });
}

export function updateWatchlist(
  id: string,
  name: string,
  description: string | null,
  realtimeEnabled = false,
) {
  return apiRequest<Watchlist>(`/api/v1/watchlists/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify({
      name,
      description,
      realtime_enabled: realtimeEnabled,
    }),
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

export function getMarketDataOverview() {
  return apiRequest<MarketDataOverview>("/api/v1/market-data/overview");
}

export function getMarketDataCoverage() {
  return apiRequest<UniverseCoverage>("/api/v1/market-data/coverage");
}

export function getMarketDataReadiness() {
  return apiRequest<ReadinessCapability[]>("/api/v1/market-data/readiness");
}

export function getMarketReferenceStatus() {
  return apiRequest<MarketReferenceStatus>("/api/v1/market-reference/status");
}

export function syncMarketReference(
  kind: "calendar" | "adjustments" | "suspensions" | "instrument-lifecycle",
  dryRun: boolean,
) {
  return apiRequest<ReferenceSyncResult>(
    `/api/v1/market-reference/${kind}/sync`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        provider: "fixture",
        universe: "research",
        max_instruments: 100,
        dry_run: dryRun,
      }),
    },
    10 * 60_000,
  );
}

export function getMarketSyncRuns() {
  return apiRequest<MarketSyncRun[]>("/api/v1/market-data/sync-runs?limit=50");
}

export function updateDailyMarketData(payload: {
  target_date: string | null;
  max_instruments: number;
  dry_run: boolean;
  continue_on_error: boolean;
}) {
  return apiRequest<DailyUpdateResult>(
    "/api/v1/market-data/daily-updates",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        provider: "baostock",
        universe_key: "research",
        ...payload,
      }),
    },
    10 * 60_000,
  );
}

export function getQualityRuns(page = 1) {
  return apiRequest<QualityRunPage>(
    `/api/v1/market-data/quality-runs?page=${page}&page_size=20`,
  );
}

export function getQualityRun(
  runId: string,
  filters: { severity?: string; issue_type?: string } = {},
) {
  const query = new URLSearchParams({ page: "1", page_size: "100" });
  if (filters.severity) query.set("severity", filters.severity);
  if (filters.issue_type) query.set("issue_type", filters.issue_type);
  return apiRequest<QualityRunDetail>(
    `/api/v1/market-data/quality-runs/${runId}?${query}`,
  );
}

export function verifyMarketDataQuality() {
  return apiRequest<QualityRunDetail>(
    "/api/v1/market-data/quality-runs",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        provider: "baostock",
        universe_key: "research",
      }),
    },
    10 * 60_000,
  );
}
