import { apiRequest } from "./client";
import type {
  ScreeningConditionDefinition,
  ScreeningParseResult,
  ScreeningPreviewResult,
  ScreeningProgress,
  ScreeningResultPage,
  ScreeningRun,
  ScreeningRunPage,
  ScreeningSpecSnapshot,
  ScreeningTemplate,
  ScreeningValidationResult,
} from "../types/screenings";

const jsonHeaders = { "Content-Type": "application/json" };

export const getScreeningTemplates = () =>
  apiRequest<ScreeningTemplate[]>("/api/v1/screening-templates");

export const getScreeningConditions = () =>
  apiRequest<ScreeningConditionDefinition[]>("/api/v1/screening-conditions");

export function parseScreeningText(input: {
  text: string;
  as_of_date: string | null;
  universe: {
    universe_key: "ALL_A_SHARES";
    excluded_instrument_ids: string[];
    exclude_st: boolean;
    exclude_bse: boolean;
    exclude_star_market: boolean;
    exclude_chinext: boolean;
  };
  allow_ai_assistance: boolean;
}) {
  return apiRequest<ScreeningParseResult>("/api/v1/screening-specs/parse", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function validateScreeningSpec(screening_spec: ScreeningSpecSnapshot) {
  return apiRequest<ScreeningValidationResult>(
    "/api/v1/screening-specs/validate",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ screening_spec }),
    },
  );
}

export function previewScreeningSpec(screening_spec: ScreeningSpecSnapshot) {
  return apiRequest<ScreeningPreviewResult>("/api/v1/screening-specs/preview", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ screening_spec }),
  });
}

export const getScreeningRuns = () =>
  apiRequest<ScreeningRunPage>(
    "/api/v1/research/screenings?page=1&page_size=20",
  );

export const getScreening = (id: string) =>
  apiRequest<ScreeningRun>(`/api/v1/research/screenings/${id}`);

export const getScreeningProgress = (id: string) =>
  apiRequest<ScreeningProgress>(`/api/v1/research/screenings/${id}/progress`);

export const getScreeningResults = (id: string) =>
  apiRequest<ScreeningResultPage>(
    `/api/v1/research/screenings/${id}/results?page=1&page_size=100`,
  );

export function createScreening(
  spec: Omit<ScreeningSpecSnapshot, "conditions"> & {
    conditions: {
      condition_key: string;
      parameters: Record<string, string | number | boolean | null>;
    }[];
    idempotency_key: string;
  },
) {
  return apiRequest<ScreeningRun>("/api/v1/research/screenings", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(spec),
  });
}
