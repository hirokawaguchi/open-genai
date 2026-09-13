export type NotebookLlmConfig = {
  enabled: boolean;
  model?: string;
  base_url?: string;
};

export type NotebookConfig = {
  enabled?: boolean;
  error?: string;
  accept?: string[];
  max_upload_bytes?: number;
  retention_days?: number;
  llm?: NotebookLlmConfig;
};

export type NotebookSessionSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  item_count?: number;
  filled_count?: number;
};

export type NotebookCitation = {
  n?: number;
  display_name: string;
  text?: string;
};

export type NotebookItem = {
  id: string;
  label: string;
  value: string;
  citations?: NotebookCitation[];
};

export type NotebookBriefing = {
  summary?: string;
  terms?: string[];
  outline?: string[];
};

export type NotebookFile = {
  id: string;
  filename: string;
  error?: string | null;
  created_at: string;
  node_count?: number;
  briefing?: NotebookBriefing;
};

export type NotebookKnowledgeRef = {
  id: string;
  scope: string;
  doc_id: string;
  source: string;
  title: string;
  created_at: string;
  node_count?: number;
  briefing?: NotebookBriefing;
};

export type NotebookMessage = {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  citations?: NotebookCitation[];
  created_at: string;
};

export type NotebookSessionDetail = {
  id: string;
  title: string;
  instruction: string;
  created_at: string;
  updated_at: string;
  items: NotebookItem[];
  files: NotebookFile[];
  knowledge_refs?: NotebookKnowledgeRef[];
  messages?: NotebookMessage[];
};
