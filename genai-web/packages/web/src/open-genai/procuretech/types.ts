export type ProcuretechSectionMeta = {
  key: string;
  title: string;
  item_no: number;
  write_cell: string;
  description: string;
  chat_placeholder: string;
};

export type ProcuretechConfig = {
  enabled: boolean;
  error?: string;
  sections?: ProcuretechSectionMeta[];
  retention_days?: number;
  max_upload_bytes?: number;
  marker_value?: string;
  llm?: { model?: string; base_url?: string };
};

export type ProcuretechMessage = {
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
};

export type ProcuretechSection = {
  key: string;
  title: string;
  item_no: number;
  write_cell: string;
  description: string;
  chat_placeholder: string;
  /** 現在ブックの書き出しセルの内容 */
  cell_value: string;
  messages: ProcuretechMessage[];
  /** 書き出し済み本文（未書き出しは null） */
  output: string | null;
  finalized: boolean;
  finalized_at: string | null;
};

export type ProcuretechSessionDetail = {
  id: string;
  filename: string;
  created_at: string;
  updated_at: string;
  sections: ProcuretechSection[];
};

export type ProcuretechSessionSummary = {
  id: string;
  filename: string;
  created_at: string;
  updated_at: string;
};

export type ProcuretechTurnResult = {
  reply: string;
  finalized: boolean;
  section: ProcuretechSection;
};
