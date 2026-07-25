import { apiRequest } from "./client";
import type {
  ScannerCatalogItem,
  ScanResultList,
  ScanRun,
  ScanRunMemberList,
  ScanRunPage,
  ScannerSessionDefault,
} from "../types/scanners";

const jsonHeaders = { "Content-Type": "application/json" };

export const getScannerCatalog = () =>
  apiRequest<ScannerCatalogItem[]>("/api/v1/scanners/catalog");

export const getScannerSessionDefault = () =>
  apiRequest<ScannerSessionDefault>("/api/v1/scanners/session-default");

export function createScanRun(body: Record<string, unknown>) {
  return apiRequest<ScanRun>("/api/v1/scan-runs", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });
}

export function getScanRuns(
  params: Record<string, string | number | undefined>,
) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return apiRequest<ScanRunPage>(`/api/v1/scan-runs?${query}`);
}

export const getScanRun = (id: string) =>
  apiRequest<ScanRun>(`/api/v1/scan-runs/${id}`);

export const getScanResults = (
  id: string,
  params: Record<string, string | number | undefined> = {},
) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const suffix = query.size ? `?${query}` : "";
  return apiRequest<ScanResultList>(`/api/v1/scan-runs/${id}/results${suffix}`);
};

export const getScanMembers = (id: string, status?: string) => {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest<ScanRunMemberList>(
    `/api/v1/scan-runs/${id}/members${query}`,
  );
};

export const cancelScanRun = (id: string) =>
  apiRequest<ScanRun>(`/api/v1/scan-runs/${id}/cancel`, {
    method: "POST",
  });
