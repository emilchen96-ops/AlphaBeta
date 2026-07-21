import { queryOptions } from "@tanstack/react-query";

import type { DemoInitialization, ResearchVerification } from "../types/demo";
import { apiRequest } from "./client";

export function fetchResearchStatus(): Promise<ResearchVerification> {
  return apiRequest<ResearchVerification>("/api/v1/demo/research-status");
}

export const researchStatusQueryOptions = queryOptions({
  queryKey: ["research-demo-status"],
  queryFn: fetchResearchStatus,
  retry: 1,
});

export function initializeResearch(
  mode: "fixture" | "existing-data",
): Promise<DemoInitialization> {
  return apiRequest<DemoInitialization>(
    "/api/v1/demo/initialize-research",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, reset_demo: false, dry_run: false }),
    },
    120_000,
  );
}

export function verifyResearch(): Promise<ResearchVerification> {
  return apiRequest<ResearchVerification>("/api/v1/demo/verify-research", {
    method: "POST",
  });
}
