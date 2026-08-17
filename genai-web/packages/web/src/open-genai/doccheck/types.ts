export type DoccheckConfig = {
  enabled?: boolean;
  error?: string;
  public_endpoint?: string;
  documents?: number;
  pending_tasks?: number;
  arbitration_count?: number;
  ocr_engine?: string;
  ppocr_backend?: string;
  official_paddleocr_available?: boolean;
  is_arm64?: boolean;
  assignees_default?: number;
  batch_assignees_default?: number;
  single_assignees_default?: number;
  ocr_normalize?: boolean;
  ocr_target_dpi?: number;
  ocr_long_edge?: number;
  /** チーム管理者またはシステム管理者のみ true */
  can_arbitrate?: boolean;
};

export type RegionTemplate = {
  id?: string;
  name: string;
  page_index?: number;
  x: number;
  y: number;
  w: number;
  h: number;
  field_type?: DoccheckFieldType;
  is_handwriting?: boolean;
  is_trap?: boolean;
  trap_answer?: string | null;
  sort_order?: number;
  /** 同一出力項目にまとめるグループ ID（横分割で自動付与） */
  group_id?: string | null;
  /** 出力時の項目名（複数行は同じ名前＋行番号で結合） */
  group_name?: string | null;
  /** 複数行フィールド内の行（0 始まり） */
  line_index?: number;
  /** 1 行内の横分割片（0 始まり） */
  part_index?: number;
  /** choice / choice_multi の選択肢ラベル */
  choice_options?: string[];
};

export type DoccheckFieldType =
  | 'text_single'
  | 'text_multi'
  | 'date'
  | 'number'
  | 'choice'
  | 'choice_multi';

/** 帳票全体の OCR モード（テンプレ単位） */
export type DoccheckOcrMode = 'ppocr' | 'fallback' | 'always';

export type FormTemplate = {
  id: string;
  name: string;
  description?: string;
  ocr_mode?: DoccheckOcrMode;
  region_count?: number;
  regions?: RegionTemplate[];
  created_at?: string;
  sample_image_path?: string | null;
  sample_image_data_url?: string;
  has_sample_image?: boolean;
  max_regions?: number;
};

export type DocumentSummary = {
  id: string;
  template_id: string;
  template_name?: string;
  title: string;
  status: string;
  created_at?: string;
};

export type DocumentDetail = DocumentSummary & {
  pages?: Array<{ id: string; page_index: number; dpi?: number }>;
  regions?: Array<{
    id: string;
    name: string;
    ocr_text?: string;
    ocr_confidence?: number;
    status: string;
    adopted_text?: string | null;
    is_trap?: boolean;
  }>;
  tasks?: Array<{
    id: string;
    token: string;
    tier: string;
    status: string;
    public_url?: string;
  }>;
  tasks_created?: number;
  demo_expected?: Record<string, string>;
};

export type CheckTask = {
  task_id?: string;
  token: string;
  status: string;
  name?: string;
  ocr_text?: string;
  ocr_confidence?: number;
  ocr_vision_text?: string;
  ocr_vision_confidence?: number;
  image_data_url?: string;
  image_url?: string;
  message?: string;
  is_trap?: boolean;
  field_type?: DoccheckFieldType;
  choice_options?: string[];
  group_name?: string | null;
  line_index?: number;
  part_index?: number;
  suggestions?: string[];
};

export type UserScore = {
  user_id: string;
  display_name?: string;
  points: number;
  checks_count: number;
  adopted_count: number;
  trap_correct?: number;
  trap_wrong?: number;
};

export type ArbitrationItem = {
  id: string;
  document_id: string;
  document_title?: string;
  name: string;
  ocr_text?: string;
  answers: Array<{
    answer_text: string;
    tier: string;
    checker_user_id?: string;
    is_blank?: boolean | number;
  }>;
};

export type BatchProgress = {
  total: number;
  completed: number;
  needs_arbitration: number;
  dispatched: number;
  ready: number;
  processing: number;
  by_status?: Record<string, number>;
  completion_ratio?: number;
};

export type BatchSummary = {
  id: string;
  name: string;
  template_id: string;
  template_name?: string;
  status: string;
  pages_per_document: number;
  auto_dispatch: boolean;
  assignees?: number;
  total_images: number;
  total_documents: number;
  processed_documents: number;
  error_count: number;
  last_error?: string | null;
  created_at?: string;
  progress: BatchProgress;
  documents?: DocumentSummary[];
  dispatched_now?: number;
};
