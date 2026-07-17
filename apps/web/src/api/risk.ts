import { apiRequest } from "./client";
import type {
  ActiveRiskLimits,
  RiskDecision,
  RiskDecisionPage,
} from "../types/risk";

const jsonHeaders = { "Content-Type": "application/json" };

export function getRiskDecisions(input: {
  page: number;
  pageSize: number;
  accountId?: string;
  instrumentId?: string;
  sourceType?: string;
  overallDecision?: string;
  evaluatedFrom?: string;
  evaluatedTo?: string;
  hasOrder?: boolean;
}) {
  const query = new URLSearchParams({
    page: String(input.page),
    page_size: String(input.pageSize),
  });
  if (input.accountId) query.set("account_id", input.accountId);
  if (input.instrumentId) query.set("instrument_id", input.instrumentId);
  if (input.sourceType) query.set("source_type", input.sourceType);
  if (input.overallDecision)
    query.set("overall_decision", input.overallDecision);
  if (input.evaluatedFrom) query.set("evaluated_from", input.evaluatedFrom);
  if (input.evaluatedTo) query.set("evaluated_to", input.evaluatedTo);
  if (input.hasOrder !== undefined)
    query.set("has_order", String(input.hasOrder));
  return apiRequest<RiskDecisionPage>(`/api/v1/risk-decisions?${query}`);
}

export function getRiskDecision(id: string) {
  return apiRequest<RiskDecision>(`/api/v1/risk-decisions/${id}`);
}

export function getActiveRiskLimits() {
  return apiRequest<ActiveRiskLimits>("/api/v1/risk-limits/active");
}

export function assessSignalRisk(
  signalId: string,
  input: {
    account_id: string;
    quantity: string | null;
    reference_price: string | null;
    idempotency_key: string;
  },
) {
  return apiRequest<RiskDecision>(
    `/api/v1/signals/${signalId}/risk-assessments`,
    { method: "POST", headers: jsonHeaders, body: JSON.stringify(input) },
  );
}
