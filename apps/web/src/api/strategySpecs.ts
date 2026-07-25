import { apiRequest } from "./client";
import type {
  StrategyParseResult,
  StrategySpec,
  StrategyTemplate,
  UserStrategy,
  UserStrategyPage,
} from "../types/strategySpecs";

const jsonHeaders = { "Content-Type": "application/json" };

export const parseStrategyText = (text: string) =>
  apiRequest<StrategyParseResult>("/api/v1/strategy-specs/parse", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ text }),
  });

export const validateStrategySpec = (spec: StrategySpec) =>
  apiRequest<{
    valid: true;
    spec: StrategySpec;
    preview: string[];
    compiled_strategy_key: string;
  }>("/api/v1/strategy-specs/validate", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ spec }),
  });

export const previewStrategySpec = (spec: StrategySpec) =>
  apiRequest<{ preview: string[] }>("/api/v1/strategy-specs/preview", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ spec }),
  });

export const listStrategyTemplates = () =>
  apiRequest<StrategyTemplate[]>("/api/v1/strategy-templates");

export const listUserStrategies = (includeArchived = false) =>
  apiRequest<UserStrategyPage>(
    `/api/v1/user-strategies?page=1&page_size=100&include_archived=${String(includeArchived)}`,
  );

export const createUserStrategy = (body: {
  name: string;
  description: string;
  spec: StrategySpec;
}) =>
  apiRequest<UserStrategy>("/api/v1/user-strategies", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });

export const updateUserStrategy = (
  id: string,
  body: { name: string; description: string; spec: StrategySpec },
) =>
  apiRequest<UserStrategy>(`/api/v1/user-strategies/${id}`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });

export const cloneUserStrategy = (id: string) =>
  apiRequest<UserStrategy>(`/api/v1/user-strategies/${id}/clone`, {
    method: "POST",
  });

export const archiveUserStrategy = (id: string) =>
  apiRequest<UserStrategy>(`/api/v1/user-strategies/${id}/archive`, {
    method: "POST",
  });
