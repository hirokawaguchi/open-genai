import { teamApi } from '@/lib/fetcher';
import type { KnowledgePick } from '@/features/chat/stores/useChatStore';

export type KnowledgePassage = {
  scope: string;
  source: string;
  title: string;
  text: string;
};

/** 選んだタグの文書だけを検索する。 */
export const searchKnowledge = (question: string, picks: KnowledgePick[]) =>
  teamApi
    .post<{ passages: KnowledgePassage[] }>('knowledge/search', {
      question,
      selections: picks.map((pick) => ({ scope: pick.scope, tag: pick.tag })),
    })
    .then((res) => res.data);

/** モデルに渡す抜粋。画面の発言には出さない。 */
export const formatKnowledgeContext = (passages: KnowledgePassage[]) => {
  if (passages.length === 0) {
    return [
      '選択したナレッジを検索しましたが、該当する抜粋はありませんでした。',
      'ナレッジにある事実として答えず、見つからなかったことを伝えてください。',
    ].join('');
  }
  const blocks = passages
    .map((passage, index) => {
      const label = passage.title || passage.source || '資料';
      return `【${index + 1}】出典: ${label}\n${passage.text}`;
    })
    .join('\n\n');
  return [
    '以下は、利用者が選んだナレッジからの抜粋です。回答はこの抜粋を根拠にしてください。',
    '抜粋に無い事実は、ナレッジの内容として書かないでください。',
    '',
    blocks,
  ].join('\n');
};
