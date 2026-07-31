import { apiRequest } from "./client";
import type {
  AIAnalysisCreateBody,
  AIAnalysisPage,
  AIAnalysisRun,
  AIProviderStatus,
  AIProviderTestResult,
  ResearchInsight,
  ResearchInsightPage,
  AIResearchReport,
  AIResearchTask,
  AIResearchTaskCreateBody,
  AIResearchTaskPage,
} from "../types/aiResearch";

const jsonHeaders = { "Content-Type": "application/json" };

export const getAIProviderStatus = () =>
  apiRequest<AIProviderStatus>("/api/v1/ai/providers/status");

export const testAIProvider = () =>
  apiRequest<AIProviderTestResult>("/api/v1/ai/providers/test", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({}),
  });

export const createAIAnalysis = (body: AIAnalysisCreateBody) =>
  apiRequest<AIAnalysisRun>("/api/v1/ai/analyses", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });

export function getAIAnalyses(params: {
  page?: number;
  page_size?: number;
  analysis_type?: string;
  status?: string;
}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return apiRequest<AIAnalysisPage>(`/api/v1/ai/analyses?${query}`);
}

export const getAIAnalysis = (id: string) =>
  apiRequest<AIAnalysisRun>(`/api/v1/ai/analyses/${id}`);

export function getResearchInsights(page = 1, pageSize = 20) {
  return apiRequest<ResearchInsightPage>(
    `/api/v1/research-insights?page=${page}&page_size=${pageSize}`,
  );
}

export const getResearchInsight = (id: string) =>
  apiRequest<ResearchInsight>(`/api/v1/research-insights/${id}`);

export const createAIResearchTask = (body: AIResearchTaskCreateBody) =>
  apiRequest<AIResearchTask>("/api/v1/ai/research-tasks", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  }, 15_000);

export function getAIResearchTasks(page = 1, pageSize = 20) {
  return apiRequest<AIResearchTaskPage>(
    `/api/v1/ai/research-tasks?page=${page}&page_size=${pageSize}`,
  );
}

export const getAIResearchTask = (id: string) =>
  apiRequest<AIResearchTask>(`/api/v1/ai/research-tasks/${id}`);

export const cancelAIResearchTask = (id: string) =>
  apiRequest<AIResearchTask>(`/api/v1/ai/research-tasks/${id}/cancel`, {
    method: "POST",
  });

export const retryAIResearchTask = (id: string) =>
  apiRequest<AIResearchTask>(`/api/v1/ai/research-tasks/${id}/retry`, {
    method: "POST",
  });

export const getAIResearchReport = (id: string) =>
  apiRequest<AIResearchReport>(`/api/v1/ai/research-tasks/${id}/report`);

export function getAIResearchExportUrl(id: string, format: "markdown" | "pdf") {
  const base = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
    /\/$/,
    "",
  );
  return `${base}/api/v1/ai/research-tasks/${id}/report/${format}`;
}
