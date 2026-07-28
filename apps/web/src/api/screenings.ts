import { apiRequest } from "./client";
import type {
  ScreeningProgress,
  ScreeningResultPage,
  ScreeningRun,
  ScreeningRunPage,
  ScreeningSpecSnapshot,
  ScreeningTemplate,
} from "../types/screenings";

const jsonHeaders = { "Content-Type": "application/json" };

export const getScreeningTemplates = () =>
  apiRequest<ScreeningTemplate[]>("/api/v1/screening-templates");

export const getScreeningRuns = () =>
  apiRequest<ScreeningRunPage>(
    "/api/v1/research/screenings?page=1&page_size=20",
  );

export const getScreening = (id: string) =>
  apiRequest<ScreeningRun>(`/api/v1/research/screenings/${id}`);

export const getScreeningProgress = (id: string) =>
  apiRequest<ScreeningProgress>(
    `/api/v1/research/screenings/${id}/progress`,
  );

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
