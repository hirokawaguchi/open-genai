export const TOOL_LABELS: Record<string, string> = {
  search_sources: 'ノートの参考資料を検索',
  list_items: '項目を確認',
  set_goal: 'ゴールを記録',
  commit_items: '項目へ書く',
  ask_user: '確認する',
  deliver: 'エディタへ渡す',
  write_office_draft: '文書台帳へ書く',
  knowledge_list_tags: '共有ナレッジのタグを一覧',
  knowledge_list_docs: '共有ナレッジの文書を一覧',
  knowledge_search: '共有ナレッジを検索',
  get_current_time: '現在の日時を確認',
  get_weather: '天気を確認',
  wikipedia_search: 'Wikipediaを検索',
  web_search: 'Wikipediaを検索',
};

/** Hermes が付ける内部名を、ノートの道具名へ戻す。探索や呼び出し ID は空。 */
export const notebookToolName = (name: string): string | null => {
  const text = name.trim();
  if (!text || text.startsWith('tool_') || text.startsWith('call_')) return null;
  const tail = text.includes('__') ? (text.split('__').pop() ?? text) : text;
  const tool = tail.split(':')[0]?.trim() ?? '';
  if (!tool || tool.startsWith('tool_') || tool.startsWith('call_')) return null;
  return tool;
};

export const toolLabel = (name: string) => {
  const tool = notebookToolName(name);
  if (!tool) return '';
  return TOOL_LABELS[tool] ?? tool;
};

export const toolLabels = (names: string[]) => names.map(toolLabel).join('、');
