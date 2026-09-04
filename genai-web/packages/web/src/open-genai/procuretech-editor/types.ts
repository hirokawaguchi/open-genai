// 情報化企画書エディタ（procuretech-editor ExApp）のフロント型定義。
// backend の /procuretech-editor/* プロキシ経由で ExApp と JSON をやり取りする。

export type EditorConfig = {
  enabled: boolean;
  error?: string;
  storage_configured?: boolean;
  generate_configured?: boolean;
  /** 生成テーマ一覧（テーマ↔ヒアリングシート↔API の紐づけ。管理者が設定） */
  generate_themes?: EditorGenerateTheme[];
  max_upload_bytes?: number;
  /** systemplan / global の識別マーカー表示名 */
  markers?: Record<string, string>;
};

export type EditorProject = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  file_count: number;
};

/** ファイル種別（backend の _kind_of と対応）。 */
export type EditorFileKind =
  | 'markdown'
  | 'text'
  | 'excel'
  | 'image'
  | 'word'
  | 'pdf'
  | 'zip'
  | 'binary'
  | 'keep';

export type EditorFile = {
  id: string;
  project_id: string;
  rel_path: string;
  kind: EditorFileKind;
  size: number;
  /** 生成結果 sections.json 由来の安定 ID（合成定義の参照キー。手動ファイルは空） */
  section_key?: string;
  created_at: string;
  updated_at: string;
};

export type EditorFileContent = {
  path: string;
  kind: EditorFileKind;
  size: number;
  updated_at: string;
  /** テキスト系（markdown/text）のとき本文 */
  content?: string;
  /** バイナリ系のとき署名付きダウンロード URL */
  download_url?: string;
};

/** 生成テーマの入力（ヒアリングシート）定義。 */
export type EditorGenerateThemeInput = {
  key: string;
  label: string;
  /** B1 マーカー（様式検証用。任意） */
  marker?: string | null;
  accept?: string;
};

/** 生成される章（section key ↔ 表示名）。 */
export type EditorThemeSection = {
  key: string;
  label: string;
};

/** テーマ既定の合成定義（出力ファイル毎の順序付き section key リスト）。 */
export type EditorThemeOutput = {
  id: string;
  name: string;
  /** markdown: 章を並べて Word 合成 / excel: 生成された単一 Excel をそのまま出力 */
  kind?: 'markdown' | 'excel';
  sections: string[];
};

/** 生成テーマ（例: 調達仕様書）。 */
export type EditorGenerateTheme = {
  id: string;
  label: string;
  description?: string;
  doc_type?: string;
  /** このテーマの生成 API が構成済みか */
  configured?: boolean;
  inputs: EditorGenerateThemeInput[];
  /** 生成される章カタログ（合成 UI のラベル表示に使用） */
  sections?: EditorThemeSection[];
  /** 既定の合成定義 */
  outputs?: EditorThemeOutput[];
};

/** 合成定義の 1 項目（section key 参照。手動ファイルは file_id 参照）。 */
export type EditorCompositionItem = {
  section_key?: string;
  file_id?: string;
};

/** 合成定義の 1 出力ファイル（順序付き section 一覧）。 */
export type EditorCompositionOutput = {
  id: string;
  name: string;
  /** markdown: 章を並べて Word 合成 / excel: 生成された単一 Excel をそのまま出力 */
  kind?: 'markdown' | 'excel';
  enabled: boolean;
  items: EditorCompositionItem[];
};

/** プロジェクトの合成定義。 */
export type EditorComposition = {
  theme: string;
  outputs: EditorCompositionOutput[];
};

/** GET /composition の応答。 */
export type EditorCompositionResponse = {
  theme: {
    id: string;
    label: string;
    doc_type?: string;
    sections: EditorThemeSection[];
    outputs: EditorThemeOutput[];
    configured?: boolean;
  };
  saved: boolean;
  composition: EditorComposition;
  files: {
    id: string;
    rel_path: string;
    kind: EditorFileKind;
    section_key?: string;
  }[];
  error?: string;
};

/** POST /compose の応答。 */
export type EditorComposeResult = {
  status?: string;
  download_url?: string;
  download_filename?: string;
  outputs?: string[];
  error?: string;
};

/** ヒアリングシート → 章別 Markdown 生成ジョブの状態。 */
export type EditorGeneration = {
  request_id?: string;
  status?: 'processing' | 'success' | 'error';
  progress?: number;
  imported?: boolean;
  /** 取り込んだ相対パス一覧（成功時） */
  files?: string[];
  error?: string;
};
