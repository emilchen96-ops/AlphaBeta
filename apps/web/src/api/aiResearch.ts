import { apiRequest } from "./client";
import type {
  AIAnalysisCreateBody,
  AIAnalysisPage,
  AIAnalysisRun,
  AIProviderStatus,
  ResearchInsight,
  ResearchInsightPage,
} from "../types/aiResearch";

const jsonHeaders = { "Content-Type": "application/json" };

export const getAIProviderStatus = () =>
  apiRequest<AIProviderStatus>("/api/v1/ai/providers/status");

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
