export type NotebookLlmConfig = {
  enabled: boolean;
  model?: string;
  base_url?: string;
};

export type NotebookMcpStatus = {
  enabled: boolean;
  shared?: boolean;
  tools?: string[];
};

export type NotebookMcp = {
  id: string;
  catalog_id: string;
  name: string;
  kind: 'builtin' | 'remote' | string;
  url: string;
  description: string;
  prompt: string;
  default_prompt?: string;
  prompt_is_default?: boolean;
  tools: string[];
  connected: boolean;
  available: boolean;
  builtin: boolean;
  enabled?: boolean;
};

export type NotebookConfig = {
  enabled?: boolean;
  error?: string;
  accept?: string[];
  max_upload_bytes?: number;
  retention_days?: number;
  llm?: NotebookLlmConfig;
  tools?: string[];
  mcp?: {
    knowledge?: NotebookMcpStatus;
    catalog?: { catalog_id: string; name: string; description: string }[];
  };
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
  ocr?: boolean;
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

export type NotebookToolTrace = {
  name: string;
  result?: string;
};

export type NotebookMessage = {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  citations?: NotebookCitation[];
  tool_trace?: NotebookToolTrace[];
  created_at: string;
};

export type NotebookSkill = {
  id: string;
  name: string;
  personality: string;
  instructions: string;
  tools: string[];
  created_at?: string;
  updated_at?: string;
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
  mcps?: NotebookMcp[];
};
