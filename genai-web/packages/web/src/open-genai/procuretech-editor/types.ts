// 情報化企画書エディタ（procuretech-editor ExApp）のフロント型定義。
// backend の /procuretech-editor/* プロキシ経由で ExApp と JSON をやり取りする。

export type EditorConfig = {
  enabled: boolean;
  error?: string;
  storage_configured?: boolean;
  convert_configured?: boolean;
  nextcloud_configured?: boolean;
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

/** 書き出し対象フラグ（外部変換 API の options）。 */
export type EditorExportOptions = {
  allow_specification?: boolean;
  allow_rfi?: boolean;
  allow_quotation?: boolean;
  allow_primaryexam?: boolean;
};

export type EditorConversion = {
  status?: string;
  request_id?: string;
  nextcloud_path?: string;
  download_url?: string;
  download_filename?: string;
  download_error?: string;
  error?: string;
  [key: string]: unknown;
};
