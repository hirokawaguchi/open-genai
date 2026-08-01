import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type { CreateTemplateInput, PromptTemplate, PromptTemplatesResponse } from './types';

export const PROMPT_TEMPLATES_KEY = 'prompts/templates';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

const fetchTemplates = async (): Promise<PromptTemplatesResponse> => {
  const res = await teamApiFetcher<PromptTemplatesResponse>(PROMPT_TEMPLATES_KEY);
  return {
    templates: res?.templates ?? [],
    canCreateStandard: !!res?.canCreateStandard,
    teams: res?.teams ?? [],
  };
};

/** テンプレート一覧・共有先チーム・作成可否を取得する。 */
export const usePromptTemplates = () => {
  const { data, error, isLoading, mutate } = useSWR<PromptTemplatesResponse>(
    PROMPT_TEMPLATES_KEY,
    fetchTemplates,
    { revalidateOnFocus: false, suspense: false },
  );

  return {
    templates: data?.templates ?? [],
    teams: data?.teams ?? [],
    canCreateStandard: data?.canCreateStandard ?? false,
    isLoading,
    loadError: error ? 'テンプレートの取得に失敗しました。時間をおいて再度お試しください。' : null,
    mutate,
  };
};

/** テンプレートの作成・削除。実行後に一覧を再取得する。 */
export const usePromptTemplateActions = (
  mutate: () => Promise<unknown>,
) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(
    async (input: CreateTemplateInput): Promise<PromptTemplate | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<{ template: PromptTemplate }>(
          PROMPT_TEMPLATES_KEY,
          input,
        );
        await mutate();
        return res.data?.template ?? null;
      } catch (e) {
        setError(errorMessage(e, 'テンプレートの作成に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [mutate],
  );

  const remove = useCallback(
    async (id: string): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        await teamApi.delete(`${PROMPT_TEMPLATES_KEY}/${encodeURIComponent(id)}`);
        await mutate();
        return true;
      } catch (e) {
        setError(errorMessage(e, 'テンプレートの削除に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [mutate],
  );

  return { create, remove, submitting, error, setError };
};
