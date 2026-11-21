import type { ExApp } from 'genai-web';
import { useParams } from 'react-router';
import { useSWRConfig } from 'swr';
import { isApiError, teamApi } from '@/lib/fetcher';

export const useMoveTeamAppOrder = () => {
  const { teamId } = useParams();
  const { mutate } = useSWRConfig();

  return {
    moveTeamApp: async (exAppId: string, direction: 'up' | 'down') => {
      const res = await teamApi.post<ExApp>(`teams/${teamId}/exapps/${exAppId}/order`, {
        direction,
      });
      // AIアプリページのカード順。管理画面の一覧は呼び出し側がすぐ入れ替える。
      await mutate((key) => key === 'exapps', undefined, { revalidate: true });
      return res.data;
    },
    errorMessage: (e: unknown) => {
      if (isApiError(e)) {
        return (e.data as { error?: string })?.error || '表示順を変更できませんでした';
      }
      return '表示順を変更できませんでした';
    },
  };
};
