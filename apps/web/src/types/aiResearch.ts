export type AIAnalysisType =
  | "EVENT_SUMMARY"
  | "INSTRUMENT_IMPACT"
  | "MULTI_EVENT_SYNTHESIS"
  | "RESEARCH_QUESTION";

export interface AIProviderStatus {
  provider_key: string;
  model_name: string;
  configured: boolean;
  real_provider_available: boolean;
  message: string;
}

export interface ResearchEvidence {
  evidence_id: string;
  information_item_id: string | null;
  market_event_id: string | null;
  evidence_text: string;
  evidence_location: string | null;
}

export interface ResearchInsight {
  insight_id: string;
  analysis_run_id: string;
  insight_type: string;
  title: string;
  summary: string;
  impact_direction: string;
  importance_score: string;
  confidence: string;
  time_horizon: string | null;
  key_facts: string[];
  uncertainties: string[];
  research_questions: string[];
  structured_output: Record<string, unknown>;
  schema_version: number;
  created_at: string;
  evidence: ResearchEvidence[];
  label: string;
}

export interface AIAnalysisRun {
  analysis_id: string;
  provider_key: string;
  model_name: string;
  analysis_type: AIAnalysisType;
  prompt_template_key: string;
  prompt_version: string;
  input_document_ids: string[];
  input_event_ids: string[];
  instrument_ids: string[];
  user_question: string | null;
  status: "CREATED" | "RUNNING" | "COMPLETED" | "FAILED";
  input_token_count: number | null;
  output_token_count: number | null;
  estimated_cost: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  error: { code: string; message: string } | null;
  correlation_id: string;
  created_at: string;
  replayed: boolean;
  insight: ResearchInsight | null;
  capabilities: Record<string, boolean>;
}

export interface AIAnalysisPage {
  items: AIAnalysisRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface ResearchInsightPage {
  items: ResearchInsight[];
  page: number;
  page_size: number;
  total: number;
}

export interface AIAnalysisCreateBody {
  analysis_type: AIAnalysisType;
  event_ids: string[];
  information_item_ids: string[];
  instrument_ids: string[];
  question: string | null;
  idempotency_key: string;
}
