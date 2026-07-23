import { apiRequest } from "./client";
import type {
  MarketDataQualityRun,
  MarketSyncRun,
  MarketTimeframe,
} from "../types/market";
import type {
  IntradayBar,
  IntradayCoverage,
  IntradayImportResult,
  IntradayProvider,
  IntradayReadiness,
} from "../types/intraday";

const jsonHeaders = { "Content-Type": "application/json" };

export const getIntradayProviders = () =>
  apiRequest<{ items: IntradayProvider[]; limits: Record<string, unknown> }>(
    "/api/v1/intraday/providers",
  );

export const getIntradayCoverage = (filters?: {
  instrumentId?: string;
  timeframe?: MarketTimeframe;
  startAt?: string;
  endAt?: string;
}) => {
  const query = new URLSearchParams();
  if (filters?.instrumentId) query.set("instrument_id", filters.instrumentId);
  if (filters?.timeframe) query.set("timeframe", filters.timeframe);
  if (filters?.startAt) query.set("start_at", filters.startAt);
  if (filters?.endAt) query.set("end_at", filters.endAt);
  const suffix = query.size ? `?${query}` : "";
  return apiRequest<{ items: IntradayCoverage[] }>(
    `/api/v1/intraday/coverage${suffix}`,
  );
};

export const getIntradayReadiness = () =>
  apiRequest<{ items: IntradayReadiness[] }>("/api/v1/intraday/readiness");

export const getIntradayImports = () =>
  apiRequest<{ items: MarketSyncRun[] }>("/api/v1/intraday/imports");

export const getIntradayQualityRuns = () =>
  apiRequest<{ items: MarketDataQualityRun[]; total: number }>(
    "/api/v1/intraday/quality-runs",
  );

export const generateIntradayFixture = (dryRun: boolean) =>
  apiRequest<IntradayImportResult>(
    "/api/v1/intraday/imports",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        provider: "D03_FIXTURE",
        source_timezone: "Asia/Shanghai",
        target_timeframes: ["MINUTE_5", "MINUTE_15", "MINUTE_30", "MINUTE_60"],
        conflict_policy: "keep_existing",
        continue_on_error: true,
        dry_run: dryRun,
      }),
    },
    120_000,
  );

export const aggregateIntraday = (payload: {
  instrument_id: string;
  start_at: string;
  end_at: string;
  targets: MarketTimeframe[];
  dry_run: boolean;
}) =>
  apiRequest<MarketSyncRun>(
    "/api/v1/intraday/aggregations",
    { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) },
    60_000,
  );

export const verifyIntradayQuality = (
  instrumentId: string,
  timeframe: MarketTimeframe = "MINUTE_1",
  startAt = "2026-07-06T00:00:00+08:00",
  endAt = "2026-07-11T00:00:00+08:00",
) =>
  apiRequest<MarketDataQualityRun>(
    "/api/v1/intraday/quality-runs",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        instrument_id: instrumentId,
        source_code: "MINIQMT",
        timeframe,
        start_at: startAt,
        end_at: endAt,
      }),
    },
    60_000,
  );

export const getIntradayBars = (
  instrumentId: string,
  timeframe: MarketTimeframe,
  adjustmentMode: "RAW" | "QFQ",
) => {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 10);
  const query = new URLSearchParams({
    instrument_id: instrumentId,
    timeframe,
    start_at: start.toISOString(),
    end_at: end.toISOString(),
    adjustment_mode: adjustmentMode,
    limit: "2000",
  });
  return apiRequest<{
    items: IntradayBar[];
    historical: true;
    realtime: false;
  }>(`/api/v1/intraday/bars?${query}`);
};
