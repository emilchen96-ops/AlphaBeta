import { queryOptions } from "@tanstack/react-query";

import type { SystemCapabilities, SystemStatus } from "../types/system";
import { apiRequest } from "./client";

export function fetchSystemStatus(): Promise<SystemStatus> {
  return apiRequest<SystemStatus>("/api/v1/system/status");
}

export const systemStatusQueryOptions = queryOptions({
  queryKey: ["system-status"],
  queryFn: fetchSystemStatus,
  refetchInterval: 10_000,
  retry: 1,
});

export function fetchSystemCapabilities(): Promise<SystemCapabilities> {
  return apiRequest<SystemCapabilities>("/api/v1/system/capabilities");
}

export const systemCapabilitiesQueryOptions = queryOptions({
  queryKey: ["system-capabilities"],
  queryFn: fetchSystemCapabilities,
  refetchInterval: 30_000,
  retry: 1,
});
