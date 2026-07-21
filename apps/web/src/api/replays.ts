import { apiRequest } from "./client";
import type {
  CreateReplayRequest,
  ReplayEquityPoint,
  ReplayEvent,
  ReplayIntegrity,
  ReplayPage,
  ReplayRun,
  ReplaySpeedMode,
  ReplayState,
} from "../types/replays";

const jsonHeaders = { "Content-Type": "application/json" };

export const createReplay = (body: CreateReplayRequest) =>
  apiRequest<ReplayRun>(
    "/api/v1/replays",
    { method: "POST", headers: jsonHeaders, body: JSON.stringify(body) },
    30_000,
  );

export const listReplays = () =>
  apiRequest<ReplayPage>("/api/v1/replays?page=1&page_size=50");

export const getReplay = (id: string) =>
  apiRequest<ReplayRun>(`/api/v1/replays/${id}`);

export const getReplayState = (id: string) =>
  apiRequest<{ state: ReplayState }>(`/api/v1/replays/${id}/state`);

export const getReplayEvents = (id: string, afterSequence = 0) =>
  apiRequest<{ items: ReplayEvent[]; total: number }>(
    `/api/v1/replays/${id}/events?after_sequence=${afterSequence}&page_size=500`,
  );

const collection = <T>(id: string, resource: string) =>
  apiRequest<{ items: T[] }>(`/api/v1/replays/${id}/${resource}`);

export const getReplayEquity = (id: string) =>
  collection<ReplayEquityPoint>(id, "equity");
export const getReplaySignals = (id: string) =>
  collection<Record<string, unknown>>(id, "signals");
export const getReplayRisks = (id: string) =>
  collection<Record<string, unknown>>(id, "risk-decisions");
export const getReplayOrders = (id: string) =>
  collection<Record<string, unknown>>(id, "orders");
export const getReplayFills = (id: string) =>
  collection<Record<string, unknown>>(id, "fills");
export const getReplayIntegrity = (id: string) =>
  apiRequest<ReplayIntegrity>(`/api/v1/replays/${id}/integrity`);

export const controlReplay = (
  id: string,
  action: "start" | "pause" | "resume" | "step" | "stop",
  expectedRunVersion: number,
) =>
  apiRequest<ReplayRun>(`/api/v1/replays/${id}/${action}`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      expected_run_version: expectedRunVersion,
      idempotency_key: `ui-${action}-${id}-${expectedRunVersion}`,
    }),
  });

export const setReplaySpeed = (
  id: string,
  speedMode: ReplaySpeedMode,
  expectedRunVersion: number,
) =>
  apiRequest<ReplayRun>(`/api/v1/replays/${id}/speed`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      speed_mode: speedMode,
      expected_run_version: expectedRunVersion,
      idempotency_key: `ui-speed-${speedMode}-${id}-${expectedRunVersion}`,
    }),
  });
