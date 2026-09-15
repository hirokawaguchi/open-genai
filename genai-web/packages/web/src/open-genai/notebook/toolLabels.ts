export const TOOL_LABELS: Record<string, string> = {
  search_sources: 'ノートの参考資料を検索',
  list_items: '採用済み項目を確認',
  knowledge_list_tags: '共有ナレッジのタグを一覧',
  knowledge_list_docs: '共有ナレッジの文書を一覧',
  knowledge_search: '共有ナレッジを検索',
  get_current_time: '現在の日時を確認',
  get_weather: '天気を確認',
  wikipedia_search: 'Wikipediaを検索',
  web_search: 'Wikipediaを検索',
};

export const toolLabel = (name: string) => TOOL_LABELS[name] ?? name;

export const toolLabels = (names: string[]) => names.map(toolLabel).join('、');
