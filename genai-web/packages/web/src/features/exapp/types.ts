type GovAIFormUIType =
  | 'text'
  | 'number'
  | 'textarea'
  | 'file'
  | 'select'
  | 'radio'
  | 'checkbox'
  | 'hidden'
  | 'preview';

export type GovAIListItem = {
  title: string;
  value: string;
  // OpenGENAI Form Spec v1 拡張: この選択肢を選んで実行する際に確認ダイアログを出す。
  // 不可逆な操作（削除・全消去など）向け。メッセージ文字列を指定する。
  confirm?: string;
};

/**
 * OpenGENAI exApp Form Spec v1 拡張: 条件表示。
 * 別フィールドの現在値が `in` に含まれる時のみ表示する。
 * 配列で複数条件を渡した場合は全条件を満たす時のみ表示（AND）。
 */
export type GovAIFormCondition = {
  field: string;
  in: string[];
};
export type GovAIFormVisibleWhen = GovAIFormCondition | GovAIFormCondition[];

export type GovAIFormUI = {
  type: GovAIFormUIType; // UIタイプ
  title: string; // タイトルラベル
  desc?: string; // サポートテキスト
  required?: boolean; // 必須かどうか（未指定の場合は任意になる）
  default_value?: string; // デフォルト値
  // --- OpenGENAI exApp Form Spec v1 拡張（加算的・opt-in。未指定なら従来動作） ---
  visibleWhen?: GovAIFormVisibleWhen; // 条件表示
  reactive?: boolean; // 値変更時に /resolve を呼びスキーマを再取得するトリガ
};

export type GovAIFormUIText = {
  min_length?: number; // 文字数の最小値
  max_length?: number; // 文字数の最大値
} & GovAIFormUI;

export type GovAIFormUINumber = {
  min?: number; // 数字の最小値
  max?: number; // 数字の最大値
} & GovAIFormUI;

export type GovAIFormUIFile = {
  multiple?: boolean; // 複数ファイルのアップロードを許可するかどうか
  accept?: string; // 受付可能なファイルのフォーマット（accept属性に設定される）（https://developer.mozilla.org/ja/docs/Web/HTML/Reference/Attributes/accept）
  max_size?: string; // ファイルの最大サイズ（KB, MB, GBで指定）（5KB, 5.8MB, 4.2GB等）
  max_file_count?: number; // アップロード可能なファイルの最大数（multipleがtrueの場合に使用される）
} & GovAIFormUI;

export type GovAIFormUITextarea = {
  min_length?: number; // 文字数の最小値
  max_length?: number; // 文字数の最大値
} & GovAIFormUI;

export type GovAIFormUISelect = {
  items?: GovAIListItem[]; // 選択肢のリスト
} & GovAIFormUI;

export type GovAIFormUICheckbox = {
  items?: GovAIListItem[]; // 選択肢のリスト
} & GovAIFormUI;

export type GovAIFormUIRadio = {
  items?: GovAIListItem[]; // 選択肢のリスト
} & GovAIFormUI;

export type GovAIFormUIHidden = {
  type: 'hidden';
  default_value: string;
};

/**
 * OpenGENAI exApp Form Spec v1 拡張: プレビュー（読み取り専用）。
 * `template` 中の {{キー}} を他フィールドの現在値で置換して表示する。
 */
export type GovAIFormUIPreview = {
  template?: string;
} & GovAIFormUI;

export type GovAIFormUIItem =
  | GovAIFormUIText
  | GovAIFormUINumber
  | GovAIFormUIFile
  | GovAIFormUITextarea
  | GovAIFormUISelect
  | GovAIFormUICheckbox
  | GovAIFormUIRadio
  | GovAIFormUIHidden
  | GovAIFormUIPreview;

export type GovAIFormUIJson = {
  [key in string]: GovAIFormUIItem;
};

export type GovAIFormDefaultValue = {
  [key in string]: string;
};

export type ConversationHistory = {
  input: string;
  output: string;
  createdDate: string;
};

export type FileInputItem = {
  files: { filename: string }[];
};
