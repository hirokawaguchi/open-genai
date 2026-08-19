/** 画面上の日本語名。後で差し替えやすいよう定数化。 */
export const PATCHFORM_LABEL = 'フォーム';

export const CATALOG_CATEGORY_LABEL: Record<string, string> = {
  basic: '基本',
  selection: '選択',
  datetime: '日時',
  composite: '自治体向け',
  display: '表示',
  advanced: '高度',
  ai: 'AI読取',
};

export const CATALOG_CATEGORY_ORDER = [
  'basic',
  'selection',
  'datetime',
  'composite',
  'display',
  'advanced',
  'ai',
];

/** 部品の使い方。API の description が無いときもツールチップで出す。 */
export const CATALOG_TYPE_HELP: Record<string, string> = {
  text: '氏名や件名など、短い文言を1行で入力してもらいます。',
  textarea: '理由や自由記述など、改行できる長い文章を入力してもらいます。',
  email: 'メールアドレスを入力し、形式を確認します。',
  phone: '電話番号を入力してもらいます。',
  number: '数量・金額・人数など、数値だけを入力してもらいます。',
  select: 'プルダウンの一覧から、1つだけ選んでもらいます。',
  radio: '並んだ選択肢から、1つだけ選んでもらいます。',
  checkbox: '当てはまるものを、複数選んでもらいます。',
  slider: 'バーを動かして、目安の数値を選んでもらいます。',
  rating: '星などで満足度や評価（1〜5）を付けてもらいます。',
  date: '年月日をカレンダーから選んでもらいます。',
  time: '時刻（時・分）を選んでもらいます。',
  'datetime-local': '日付と時刻をまとめて選んでもらいます。',
  daterange: '開始日と終了日の期間を入力してもらいます。',
  address_composite: '郵便番号から住所を補完し、都道府県・市区町村・町名などをまとめて聞きます。',
  user_info_composite: '姓・名・フリガナをまとめて聞きます。性別と生年月日は表示するかを選べます。',
  company_info_composite: '法人番号から法人名を補完し、代表者もまとめて聞きます。',
  financial_institution_composite:
    '振込先を聞きます。ゆうちょは記号・番号から店番と口座番号へ換算します。',
  text_display: '回答欄ではなく、案内や注意書きの文章を表示します。',
  image_display: '案内図などの画像を表示します。回答は集まりません。',
  divider: '項目の区切り線を入れます。回答は集まりません。',
  page_break: 'ここから次のページです。回答者には進捗と「次へ」が出ます。',
  file: '添付ファイルを受け取り、実ファイルを保管します。',
  password: '入力中の文字を隠して表示します。',
  calculated: 'ほかの数値部品から、金額などをその場で自動計算して表示します。',
  mynumber: 'マイナンバー12桁を入力します。庁内専用で、保存時に暗号化します。',
  matrix_question: '行×列の表で、各項目の回答を選んでもらいます。',
  signature_pad: '署名画像を添付し、実ファイルとして保管します。',
  location: '緯度経度や現在地など、位置情報を入力してもらいます。',
  qr_scanner: 'QRコードの内容を読み取るか、手入力してもらいます。',
  image_recognition: '写真や画像から文字を読み取り、入力を補助します。',
  document_reader: 'テキスト文書から内容を取り出し、入力を補助します。',
};

export const catalogTypeHelp = (type: string, fallback?: string | null) =>
  CATALOG_TYPE_HELP[type] || fallback || '';
