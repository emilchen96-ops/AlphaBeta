import { queryOptions } from "@tanstack/react-query";

import type { SystemStatus } from "../types/system";
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
