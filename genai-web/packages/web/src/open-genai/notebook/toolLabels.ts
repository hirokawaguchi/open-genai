export const TOOL_LABELS: Record<string, string> = {
  search_sources: 'ノートの参考資料を検索',
  list_items: 'クリップを確認',
  set_goal: 'ゴールを記録',
  commit_items: 'クリップへ書く',
  ask_user: '確認する',
  write_manuscript: '原稿を書く',
  fact_check: '事実を確かめる',
  revise_manuscript: '言い回しを整える',
  deliver: 'エディタで開く',
  open_draft: '原稿を開く',
  write_office_draft: '文書台帳へ書く',
  knowledge_list_tags: '共有ナレッジのタグを一覧',
  knowledge_list_docs: '共有ナレッジの文書を一覧',
  knowledge_search: '共有ナレッジを検索',
  get_current_time: '現在の日時を確認',
  get_weather: '天気を確認',
  wikipedia_search: 'Wikipediaを検索',
  web_search: 'Wikipediaを検索',
  firecrawl_search: 'Webを検索',
  firecrawl_scrape: 'Webページを読む',
  search_meetings: '会議を検索',
  search_utterances: '会議録を検索',
  get_meeting: '会議を開く',
  get_utterance: '発言を確認',
  find_agenda: '議題を検索',
  list_stances: 'スタンスを確認',
  list_docs: '計画の文書を一覧',
  search_plans: '計画を本文検索',
  get_section: '節を確認',
  get_doc_outline: '目次を確認',
  find_measures: '施策を検索',
  get_measure: '施策を開く',
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
