export interface InformationSource {
  source_id: string;
  source_key: string;
  display_name: string;
  source_type: string;
  base_url: string | null;
  enabled: boolean;
  configuration: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface InformationDetail {
  item_id: string;
  raw_document_id: string;
  event_id: string;
  source: InformationSource;
  title: string;
  content: string;
  raw_title: string;
  raw_content: string;
  source_url: string | null;
  published_at: string;
  received_at: string;
  event_type: string;
  direction: string;
  summary: string | null;
  importance: string | null;
  status: string;
  instruments: Array<{
    instrument_id: string;
    symbol: string;
    exchange: string;
    name: string;
  }>;
  themes: Array<{ theme_key: string; theme_name: string }>;
  duplicate: boolean;
  capabilities: Record<string, boolean>;
}

export interface InformationPage {
  items: InformationDetail[];
  page: number;
  page_size: number;
  total: number;
}
