export const RECOMMENDED_APP_OPTIONS = [
  { id: 'chat', label: 'チャット' },
  { id: 'generate', label: '文章を生成' },
  { id: 'translate', label: '翻訳' },
  { id: 'image', label: '画像を生成' },
  { id: 'diagram', label: 'ダイアグラムを生成' },
  { id: 'whisper', label: '文字起こし' },
  { id: 'prompt', label: 'プロンプトテンプレート' },
  { id: 'chosei', label: '日程調整' },
  { id: 'doccheck', label: '書類読取とチェック' },
  { id: 'patchform', label: 'フォーム' },
  { id: 'docmaker', label: 'マイ手続き' },
  { id: 'procuretech-navigator', label: '情報化企画書ナビ' },
  { id: 'procuretech-editor', label: 'Markdown エディタ' },
  { id: 'knowledge', label: 'ナレッジ管理' },
  { id: 'rag', label: 'ナレッジ検索' },
  { id: 'notebook', label: 'ノートブック' },
  { id: 'ssh', label: 'SSH 端末' },
] as const;

export type RecommendedAppId = (typeof RECOMMENDED_APP_OPTIONS)[number]['id'];
