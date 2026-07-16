import { apiRequest } from "./client";
import type {
  StrategyCatalogItem,
  StrategyRun,
  StrategyRunPage,
  StrategySignalPage,
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
