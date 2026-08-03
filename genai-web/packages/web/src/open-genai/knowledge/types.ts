// ナレッジ管理 専用ページ（/knowledge）の型定義。
// backend の /knowledge/* 認可付きプロキシ（rag-app 構造化 REST）に対応する。

/** 操作対象のスコープ（共有ナレッジ or 所属チーム）。 */
export type KnowledgeScope = {
  /** teamId。共有ナレッジは固定 ID。 */
  scope: string;
  /** 表示名。 */
  name: string;
  kind: 'common' | 'team';
  /** このスコープで書込（登録・タグ編集・削除）できるか。 */
  canManage: boolean;
};

export type ScopesResponse = {
  scopes: KnowledgeScope[];
  isSystemAdmin: boolean;
};

/** タグ（レジストリ + 使用中チャンク数）。 */
export type KnowledgeTag = {
  tag: string;
  /** 付与済みチャンク数。0 は未使用（検索対象外）。 */
  chunks: number;
};

export type TagsResponse = {
  scope: string;
  tags: KnowledgeTag[];
};

/** 登録済みドキュメント（ファイル / URL）。 */
export type KnowledgeDoc = {
  doc_id: string;
  scope: string;
  /** ファイル名 or URL。削除・タグ付け替えのキー。 */
  source: string;
  tags: string[];
  page_count: number;
  char_count: number;
  truncated?: boolean;
  content_hash?: string;
  /** 索引種別。 */
  index_kind: 'tree' | 'fulltext';
  /** 非同期登録の状態。 */
  ingest_status?: 'queued' | 'processing' | 'ready' | 'failed';
  ingest_error?: string;
  /** 個人情報検知。 */
  pii_status?: 'pending' | 'clear' | 'suspected' | 'error';
  pii_labels?: string[];
  /** 検知箇所の抜粋（警告表示用） */
  pii_hits?: Array<{
    category: string;
    match: string;
    context: string;
    offset?: number;
  }>;
  created_at?: string;
  updated_at?: string;
};

export type DocsResponse = {
  scope: string;
  documents: KnowledgeDoc[];
};

/** ドキュメント登録の取り込み種別。 */
export type RegisterMode = 'tree' | 'fulltext';

/** クライアントで base64 化した添付ファイル。 */
export type UploadFile = {
  filename: string;
  /** base64（data URL の , 以降）。 */
  content: string;
  media_type: string;
};

export type RegisterResult = {
  ok: boolean;
  scope: string;
  mode: RegisterMode;
  documents: Array<{
    doc_id: string;
    source: string;
    page_count: number;
    char_count?: number;
    node_count?: number;
    vector_chunks: number;
  }>;
};
