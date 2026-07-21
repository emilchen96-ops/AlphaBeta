export type VerificationStatus =
  "READY" | "PARTIAL" | "NOT_READY" | "DISABLED" | "FAILED" | "NOT_IMPLEMENTED";

export interface DemoStep {
  key: string;
  status: VerificationStatus;
  message: string;
  entity_id: string | null;
  replayed: boolean;
}

export interface DemoInitialization {
  status: VerificationStatus;
  mode: "fixture" | "existing-data";
  dry_run: boolean;
  steps: DemoStep[];
  required_actions: string[];
}

export interface VerificationItem {
  key: string;
  label: string;
  status: VerificationStatus;
  reason: string;
  evidence: Record<string, unknown>;
  required_actions: string[];
  link: string | null;
  available: boolean;
  checked_at: string;
}

export interface ResearchVerification {
  status: VerificationStatus;
  generated_at: string;
  items: VerificationItem[];
}
