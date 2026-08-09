import { apiRequest } from "./client";
import type {
  ScreeningConditionDefinition,
  ScreeningConditionCategory,
  ScreeningParseResult,
  ScreeningPreviewResult,
  ScreeningProgress,
  ScreeningResultPage,
  ScreeningRun,
  ScreeningRunPage,
  ScreeningSpecSnapshot,
  ScreeningTemplate,
  ScreeningValidationResult,
  ScreeningWatchlistResult,
  UserScreening,
  UserScreeningPage,
} from "../types/screenings";

const jsonHeaders = { "Content-Type": "application/json" };

export const getScreeningTemplates = () =>
  apiRequest<ScreeningTemplate[]>("/api/v1/screening-templates");

export const getScreeningTemplate = (key: string) =>
  apiRequest<ScreeningTemplate>(`/api/v1/screening-templates/${key}`);

export const getScreeningConditions = () =>
  apiRequest<ScreeningConditionDefinition[]>("/api/v1/screening-conditions");

export const getScreeningConditionCategories = () =>
  apiRequest<ScreeningConditionCategory[]>(
    "/api/v1/screening-condition-categories",
  );

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

export function getScreeningRuns(filters?: {
  status?: string;
  as_of_from?: string;
  as_of_to?: string;
  plan_name?: string;
  source_type?: "TEMPLATE" | "CUSTOM";
}) {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return apiRequest<ScreeningRunPage>(
    `/api/v1/research/screenings?${params.toString()}`,
  );
}

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
    use_existing_data_only?: boolean;
  },
) {
  return apiRequest<ScreeningRun>("/api/v1/research/screenings", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(spec),
  });
}

export const listUserScreenings = (includeArchived = true) =>
  apiRequest<UserScreeningPage>(
    `/api/v1/user-screenings?page=1&page_size=100&include_archived=${includeArchived}`,
  );

export function saveUserScreening(input: {
  name: string;
  description: string | null;
  source_text: string | null;
  screening_spec: ScreeningSpecSnapshot;
  origin: string;
}) {
  return apiRequest<UserScreening>("/api/v1/user-screenings", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function updateUserScreening(
  id: string,
  input: {
    name: string;
    description: string | null;
    source_text: string | null;
    screening_spec: ScreeningSpecSnapshot;
    origin: string;
  },
) {
  return apiRequest<UserScreening>(`/api/v1/user-screenings/${id}`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export const cloneUserScreening = (id: string) =>
  apiRequest<UserScreening>(`/api/v1/user-screenings/${id}/clone`, {
    method: "POST",
  });

export const archiveUserScreening = (id: string) =>
  apiRequest<UserScreening>(`/api/v1/user-screenings/${id}/archive`, {
    method: "POST",
  });

export const restoreUserScreening = (id: string) =>
  apiRequest<UserScreening>(`/api/v1/user-screenings/${id}/restore`, {
    method: "POST",
  });

export function runUserScreening(
  id: string,
  asOfDate: string,
  useExistingDataOnly = false,
) {
  return apiRequest<ScreeningRun>(`/api/v1/user-screenings/${id}/run`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      as_of_date: asOfDate,
      idempotency_key: `screening:${crypto.randomUUID()}`,
      use_existing_data_only: useExistingDataOnly,
    }),
  });
}

export const cancelScreening = (id: string) =>
  apiRequest<ScreeningRun>(`/api/v1/research/screenings/${id}/cancel`, {
    method: "POST",
  });

export const retryFailedScreening = (id: string) =>
  apiRequest<ScreeningRun>(`/api/v1/research/screenings/${id}/retry-failed`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      idempotency_key: `screening-retry:${crypto.randomUUID()}`,
    }),
  });

export function addScreeningResultsToWatchlist(
  screeningId: string,
  input: {
    instrument_ids: string[];
    watchlist_id: string | null;
    new_watchlist_name: string | null;
    realtime_monitor: boolean;
  },
) {
  return apiRequest<ScreeningWatchlistResult>(
    `/api/v1/research/screenings/${screeningId}/add-to-watchlist`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
  );
}
