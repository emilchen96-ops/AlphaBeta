import { apiRequest } from "./client";
import type {
  BacktestEquityPoint,
  BacktestFill,
  BacktestIntegrity,
  BacktestMetrics,
  BacktestOrder,
  BacktestPage,
  BacktestRiskDecision,
  BacktestRun,
  BacktestSignal,
  BacktestTimelineEvent,
  BacktestTrade,
  CreateBacktestRequest,
} from "../types/backtests";

const jsonHeaders = { "Content-Type": "application/json" };

export const createBacktest = (body: CreateBacktestRequest) =>
  apiRequest<BacktestRun>(
    "/api/v1/backtests",
    { method: "POST", headers: jsonHeaders, body: JSON.stringify(body) },
    120_000,
  );

export const listBacktests = (page = 1) =>
  apiRequest<BacktestPage>(
    `/api/v1/research/backtests?page=${page}&page_size=100`,
  );

export const getBacktest = (id: string) =>
  apiRequest<BacktestRun>(`/api/v1/backtests/${id}`);

export const getBacktestMetrics = (id: string) =>
  apiRequest<{ metrics: BacktestMetrics }>(`/api/v1/backtests/${id}/metrics`);

const collection = <T>(id: string, resource: string) =>
  apiRequest<{ items: T[] }>(`/api/v1/backtests/${id}/${resource}`);

export const getBacktestEquity = (id: string) =>
  collection<BacktestEquityPoint>(id, "equity-curve");
export const getBacktestTrades = (id: string) =>
  collection<BacktestTrade>(id, "trades");
export const getBacktestSignals = (id: string) =>
  collection<BacktestSignal>(id, "signals");
export const getBacktestRisks = (id: string) =>
  collection<BacktestRiskDecision>(id, "risk-decisions");
export const getBacktestOrders = (id: string) =>
  collection<BacktestOrder>(id, "orders");
export const getBacktestFills = (id: string) =>
  collection<BacktestFill>(id, "fills");
export const getBacktestTimeline = (id: string) =>
  collection<BacktestTimelineEvent>(id, "timeline");
export const getBacktestIntegrity = (id: string) =>
  apiRequest<BacktestIntegrity>(`/api/v1/backtests/${id}/integrity`);
