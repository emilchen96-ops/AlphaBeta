import { apiRequest } from "./client";
import type {
  BacktestBatch,
  BacktestBatchRequest,
  BacktestBatchResult,
  BacktestBatchSummary,
  QuickBacktestRequest,
  StrategyParseResult,
  StrategySpec,
  StrategyTemplate,
  UserStrategy,
  UserStrategyPage,
} from "../types/strategySpecs";
import type { BacktestRun } from "../types/backtests";

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

export const createQuickBacktest = (body: QuickBacktestRequest) =>
  apiRequest<BacktestRun>(
    "/api/v1/research/quick-backtests",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
    120_000,
  );

export const createBacktestBatch = (body: BacktestBatchRequest) =>
  apiRequest<BacktestBatch>(
    "/api/v1/research/backtest-batches",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
    120_000,
  );

export const getBacktestBatch = (id: string) =>
  apiRequest<BacktestBatch>(`/api/v1/research/backtest-batches/${id}`);

export const listBacktestBatches = () =>
  apiRequest<{
    items: BacktestBatch[];
    page: number;
    page_size: number;
    total: number;
  }>("/api/v1/research/backtest-batches?page=1&page_size=100");

export const getBacktestBatchResults = (id: string, page = 1, pageSize = 50) =>
  apiRequest<{
    items: BacktestBatchResult[];
    page: number;
    page_size: number;
    total: number;
  }>(
    `/api/v1/research/backtest-batches/${id}/results?page=${page}&page_size=${pageSize}`,
  );

export const getBacktestBatchSummary = (id: string) =>
  apiRequest<BacktestBatchSummary>(
    `/api/v1/research/backtest-batches/${id}/summary`,
  );

export const backtestBatchCsvUrl = (id: string) =>
  `/api/v1/research/backtest-batches/${id}/export.csv`;

export const getResearchBacktest = (id: string) =>
  apiRequest<BacktestRun>(`/api/v1/research/backtests/${id}`);

export const getResearchBacktestSummary = (id: string) =>
  apiRequest<{
    run_id: string;
    status: string;
    metrics: import("../types/backtests").BacktestMetrics | null;
    signals_generated: number;
    fills_generated: number;
    explanation: string[];
    strategy_preview: string[];
    simulation_notice: string;
  }>(`/api/v1/research/backtests/${id}/summary`);
