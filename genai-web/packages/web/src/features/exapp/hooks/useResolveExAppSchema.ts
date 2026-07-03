import { useCallback } from 'react';
import { teamApi } from '@/lib/fetcher';
import { GovAIFormUIJson } from '../types';

type ResolveResponse = {
  placeholder: GovAIFormUIJson;
};

/**
 * OpenGENAI exApp Form Spec v1: リアクティブ解決。
 * 現在のフォーム入力値を exApp に送り、再計算されたフォーム定義(placeholder)を取得する。
 * reactive フィールドの変更時に呼び出してスキーマを差し替えるために使う。
 */
export const useResolveExAppSchema = (teamId: string, exAppId: string) => {
  const resolve = useCallback(
    async (inputs: Record<string, unknown>): Promise<GovAIFormUIJson | null> => {
      if (!teamId || !exAppId) {
        return null;
      }
      try {
        const res = await teamApi.post<ResolveResponse>('exapps/resolve', {
          teamId,
          exAppId,
          inputs,
        });
        return res.data?.placeholder ?? null;
      } catch {
        return null;
      }
    },
    [teamId, exAppId],
  );

  return { resolve };
};
