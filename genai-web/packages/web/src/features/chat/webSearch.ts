import { teamApi } from '@/lib/fetcher';

export type WebSearchPassage = {
  title: string;
  url: string;
  text: string;
};

/** 検索クエリを文脈に合わせて言い換えるための直近の会話。 */
export type WebSearchHistory = { role: string; content: string }[];

/** Web 検索が使えるか（FIRECRAWL_URL 未設定なら false）。 */
export const fetchWebSearchEnabled = () =>
  teamApi
    .get<{ enabled: boolean }>('web-search/config')
    .then((res) => !!res.data?.enabled)
    .catch(() => false);

/**
 * 利用者の発話をクエリに Web を検索する。
 * history を渡すと、サーバ側で会話を踏まえた検索クエリに言い換える（「もっと詳しく」等の追い質問対応）。
 */
export const searchWeb = (query: string, history?: WebSearchHistory) =>
  teamApi
    .post<{ passages: WebSearchPassage[]; query?: string }>('web-search', { query, history })
    .then((res) => res.data);

/** モデルに渡す抜粋。画面の発言には出さない。回答に出典 URL を書かせる。 */
export const formatWebSearchContext = (passages: WebSearchPassage[]) => {
  if (passages.length === 0) {
    return [
      'Web を検索しましたが、該当する結果はありませんでした。',
      '憶測で答えず、見つからなかったことを伝えてください。',
    ].join('');
  }
  const blocks = passages
    .map((passage, index) => {
      const label = passage.title || passage.url || `結果${index + 1}`;
      return `【${index + 1}】${label}\nURL: ${passage.url}\n${passage.text}`;
    })
    .join('\n\n');
  return [
    '以下は、Web 検索で得た抜粋です。回答はこの抜粋と URL だけを根拠にしてください。',
    '抜粋に無い事実は、Web の内容として書かないでください。',
    '回答の末尾に、使った情報の「出典」としてタイトルと URL を箇条書きで示してください。',
    '',
    blocks,
  ].join('\n');
};
