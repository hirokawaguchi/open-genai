import { InvokeExAppHistory, ListInvokeExAppHistoriesResponse } from 'genai-web';
import { useMemo } from 'react';
import useSWR from 'swr';
import { teamApiFetcher } from '@/lib/fetcher';

// チャット（Dify チャットフロー連携）の「過去の会話」1 件分。
// exapp_histories の各レコードは 1 往復（ユーザー発話 + 回答）に対応するため、
// 同一 sessionId のレコードをまとめて 1 つの会話として扱う。
export type ExAppConversation = {
  sessionId: string;
  // 会話一覧に表示するタイトル（会話の最初のユーザー発話）。
  title: string;
  // 会話内で最も新しいレコードの作成日時（会話一覧の並び順に使う）。
  updatedAt: string;
  // 往復数（レコード数）。
  turnCount: number;
  // 復元用に古い順（createdDate 昇順）で保持する。
  histories: InvokeExAppHistory[];
};

const pickQuery = (history: InvokeExAppHistory): string => {
  const query = (history.inputs as { query?: unknown })?.query;
  return typeof query === 'string' ? query.trim() : '';
};

export const useExAppConversations = (teamId: string, exAppId: string) => {
  const key =
    teamId && exAppId
      ? `exapps/histories?${new URLSearchParams({ teamId, exAppId }).toString()}`
      : null;

  const { data, isLoading, error, mutate } = useSWR<ListInvokeExAppHistoriesResponse>(
    key,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );

  const conversations = useMemo<ExAppConversation[]>(() => {
    const histories = data?.history ?? [];

    const groups = new Map<string, InvokeExAppHistory[]>();
    for (const history of histories) {
      const sessionId = history.sessionId;
      if (!sessionId) {
        // sessionId を持たない旧レコードは会話として復元できないため除外。
        continue;
      }
      const items = groups.get(sessionId) ?? [];
      items.push(history);
      groups.set(sessionId, items);
    }

    const result: ExAppConversation[] = [];
    for (const [sessionId, items] of groups) {
      const asc = [...items].sort((a, b) => a.createdDate.localeCompare(b.createdDate));
      const title = asc.map(pickQuery).find((q) => q.length > 0) ?? '（無題の会話）';
      result.push({
        sessionId,
        title,
        updatedAt: asc[asc.length - 1].createdDate,
        turnCount: asc.length,
        histories: asc,
      });
    }

    // 会話一覧は最新更新順（新しい会話が上）。
    result.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    return result;
  }, [data]);

  return { conversations, isLoading, error, mutate };
};
