export type AIAnalysisType =
  | "EVENT_SUMMARY"
  | "INSTRUMENT_IMPACT"
  | "MULTI_EVENT_SYNTHESIS"
  | "RESEARCH_QUESTION";

export interface AIProviderStatus {
  provider_key: string;
  model: string;
  model_name: string;
  selectable_models: string[];
  configured: boolean;
  available: boolean;
  mode:
    | "DISABLED"
    | "FAKE"
    | "REAL_CONFIGURED"
    | "REAL_AVAILABLE"
    | "REAL_UNAVAILABLE";
  real_provider_available: boolean;
  base_url_summary: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error_code: string | null;
  capabilities: string[];
  warnings: string[];
  message: string;
}

export interface AIProviderTestResult {
  success: boolean;
  provider_key: string;
  model_name: string;
  mode: AIProviderStatus["mode"];
  latency_ms: number | null;
  error_code: string | null;
  warnings: string[];
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
  total_token_count: number | null;
  estimated_cost: string | null;
  cost_currency: string | null;
  is_real_provider: boolean;
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

export type AIResearchDepth = "FAST" | "STANDARD" | "DEEP";
export type AIResearchTaskStatus =
  | "CREATED"
  | "PREPARING_DATA"
  | "RUNNING_AGENTS"
  | "DEBATING"
  | "RISK_REVIEW"
  | "GENERATING_REPORT"
  | "COMPLETED"
  | "PARTIALLY_COMPLETED"
  | "FAILED"
  | "CANCELED";

export interface AIResearchAgentStep {
  step_id: string;
  role: string;
  role_label: string;
  ordinal: number;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";
  title: string;
  summary: string;
  structured_output: Record<string, unknown>;
  citations: Array<Record<string, unknown>>;
  input_token_count: number | null;
  output_token_count: number | null;
  error: { code: string; message: string } | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AIResearchReportSummary {
  report_id: string;
  title: string;
  executive_summary: string;
  stance: string;
  confidence: string;
  schema_version: number;
  created_at: string;
}

export interface AIResearchWorkflowEvent {
  event_id: string;
  sequence: number;
  event_type: string;
  status: string;
  node_name: string;
  agent_role: string | null;
  tool_name: string | null;
  payload: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AIResearchArtifact {
  artifact_id: string;
  artifact_key: string;
  artifact_type: string;
  title: string;
  content_markdown: string;
  ordinal: number;
  metadata: Record<string, unknown>;
  source_ids: string[];
  created_at: string;
}

export interface AIResearchTask {
  task_id: string;
  instrument: { id: string; symbol: string; exchange: string; name: string };
  question: string;
  depth: AIResearchDepth;
  start_date: string;
  end_date: string;
  provider_key: string;
  model_name: string;
  engine_key: string;
  engine_version: string;
  checkpoint_key: string;
  execution_attempt: number;
  last_checkpoint_at: string | null;
  is_real_provider: boolean;
  status: AIResearchTaskStatus;
  progress_percent: number;
  current_stage: string;
  warnings: string[];
  error: { code: string; message: string } | null;
  correlation_id: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  steps: AIResearchAgentStep[];
  events: AIResearchWorkflowEvent[];
  artifacts: AIResearchArtifact[];
  report: AIResearchReportSummary | null;
  capabilities: Record<string, boolean>;
}

export interface AIResearchTaskPage {
  items: AIResearchTask[];
  page: number;
  page_size: number;
  total: number;
}

export interface AIResearchReport extends AIResearchReportSummary {
  task_id: string;
  sections: Record<string, unknown>;
  citations: Array<Record<string, unknown>>;
  limitations: string[];
  markdown: string;
  disclaimer: string;
}

export interface AIResearchTaskCreateBody {
  instrument_id: string;
  model_name: string;
  question: string;
  depth: AIResearchDepth;
  start_date: string;
  end_date: string;
  idempotency_key: string;
}
