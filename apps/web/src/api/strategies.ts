import { apiRequest } from "./client";
import type {
  CreateStrategyExperimentRequest,
  StrategyCatalogItem,
  StrategyExperiment,
  StrategyExperimentComparisonRow,
  StrategyExperimentPage,
  StrategyExperimentRun,
  StrategyRun,
  StrategyRunPage,
  StrategySignalPage,
  StrategySignalOverlap,
} from "../types/strategies";

const jsonHeaders = { "Content-Type": "application/json" };

export const getStrategyCatalog = () =>
  apiRequest<StrategyCatalogItem[]>("/api/v1/strategies/catalog");

export function createStrategyRun(body: Record<string, unknown>) {
  return apiRequest<StrategyRun>("/api/v1/strategy-runs", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });
}

export function getStrategyRuns(
  params: Record<string, string | number | undefined>,
) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return apiRequest<StrategyRunPage>(`/api/v1/strategy-runs?${query}`);
}

export const getStrategyRun = (id: string) =>
  apiRequest<StrategyRun>(`/api/v1/strategy-runs/${id}`);

export function getSignals(
  params: Record<string, string | number | undefined>,
) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return apiRequest<StrategySignalPage>(`/api/v1/signals?${query}`);
}

export function getRunSignals(id: string, page = 1) {
  return apiRequest<StrategySignalPage>(
    `/api/v1/strategy-runs/${id}/signals?page=${page}&page_size=20`,
  );
}

export function createStrategyExperiment(
  body: CreateStrategyExperimentRequest,
  signal?: AbortSignal,
) {
  return apiRequest<StrategyExperiment>(
    "/api/v1/strategy-experiments",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
      signal,
    },
    120_000,
  );
}

export function listStrategyExperiments(
  params: Record<string, string | number | undefined>,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return apiRequest<StrategyExperimentPage>(
    `/api/v1/strategy-experiments?${query}`,
    { signal },
  );
}

export const getStrategyExperiment = (id: string, signal?: AbortSignal) =>
  apiRequest<StrategyExperiment>(`/api/v1/strategy-experiments/${id}`, {
    signal,
  });

export const listStrategyExperimentRuns = (id: string, signal?: AbortSignal) =>
  apiRequest<StrategyExperimentRun[]>(
    `/api/v1/strategy-experiments/${id}/runs`,
    { signal },
  );

export const getStrategyExperimentComparison = (
  id: string,
  signal?: AbortSignal,
) =>
  apiRequest<StrategyExperimentComparisonRow[]>(
    `/api/v1/strategy-experiments/${id}/comparison`,
    { signal },
  );

export const getStrategyExperimentSignalOverlap = (
  id: string,
  signal?: AbortSignal,
) =>
  apiRequest<StrategySignalOverlap[]>(
    `/api/v1/strategy-experiments/${id}/signal-overlap`,
    { signal },
  );
