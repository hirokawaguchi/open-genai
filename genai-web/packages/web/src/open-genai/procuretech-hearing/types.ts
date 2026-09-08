export type HearingLlmConfig = {
  enabled: boolean;
  model?: string;
  base_url?: string;
};

export type HearingConfig = {
  enabled?: boolean;
  error?: string;
  accept?: string[];
  max_upload_bytes?: number;
  retention_days?: number;
  llm?: HearingLlmConfig;
};

export type HearingSessionSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type HearingItem = {
  id: string;
  label: string;
  value: string;
};

export type HearingFile = {
  id: string;
  filename: string;
  error?: string | null;
  created_at: string;
};

export type HearingSessionDetail = {
  id: string;
  title: string;
  instruction: string;
  created_at: string;
  updated_at: string;
  items: HearingItem[];
  files: HearingFile[];
};
