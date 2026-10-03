import { useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type { NishukanHome, NishukanIssue } from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useNishukanConfig = () => {
  const { data, isLoading } = useSWR<{ enabled?: boolean; error?: string }>(
    'nishukan/config',
    async () => {
      try {
        return await teamApiFetcher<{ enabled?: boolean; error?: string }>('nishukan/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as { error?: string } | undefined;
          return { enabled: false, error: data?.error };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    isLoading,
    unavailable: data?.enabled === false,
    error: data?.error,
  };
};

export const useNishukanHome = (teamId: string | null, enabled = true) => {
  const key = !enabled
    ? null
    : teamId
      ? `nishukan/home?teamId=${encodeURIComponent(teamId)}`
      : 'nishukan/home';
  const { data, error, isLoading, mutate } = useSWR<NishukanHome>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    home: data,
    isLoading,
    loadError: error ? errorMessage(error, '台帳を読み込めませんでした。') : null,
    mutate,
  };
};

export const useNishukanActions = () => {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async <T>(work: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (e) {
      setError(errorMessage(e, '保存できませんでした。'));
      return null;
    } finally {
      setBusy(false);
    }
  };

  return {
    error,
    setError,
    busy,
    appointChief: (teamId: string, userId: string) =>
      run(() => teamApi.put(`nishukan/teams/${teamId}/chief`, { userId }).then((r) => r.data)),
    setHeadcount: (teamId: string, headcount: number) =>
      run(() => teamApi.put(`nishukan/teams/${teamId}/headcount`, { headcount }).then((r) => r.data)),
    setVacation: (teamId: string, timeboxStart: string, size: number) =>
      run(() =>
        teamApi.put(`nishukan/teams/${teamId}/vacation`, { timeboxStart, size }).then((r) => r.data),
      ),
    createProject: (body: Record<string, unknown>) =>
      run(() => teamApi.post('nishukan/projects', body).then((r) => r.data)),
    updateProject: (projectId: string, body: Record<string, unknown>) =>
      run(() => teamApi.patch(`nishukan/projects/${projectId}`, body).then((r) => r.data)),
    deleteProject: (projectId: string) =>
      run(() => teamApi.delete(`nishukan/projects/${projectId}`).then((r) => r.data)),
    createTemplate: (body: Record<string, unknown>) =>
      run(() => teamApi.post('nishukan/templates', body).then((r) => r.data)),
    updateTemplate: (templateId: string, body: Record<string, unknown>) =>
      run(() => teamApi.patch(`nishukan/templates/${templateId}`, body).then((r) => r.data)),
    deleteTemplate: (templateId: string) =>
      run(() => teamApi.delete(`nishukan/templates/${templateId}`).then((r) => r.data)),
    arrive: (templateId: string, title?: string) =>
      run(() =>
        teamApi
          .post<NishukanIssue>(`nishukan/templates/${templateId}/arrivals`, title ? { title } : {})
          .then((r) => r.data),
      ),
    undo: (issueId: string) =>
      run(() => teamApi.delete(`nishukan/issues/${issueId}`).then((r) => r.data)),
    createIssue: (body: Record<string, unknown>) =>
      run(() => teamApi.post<NishukanIssue>('nishukan/issues', body).then((r) => r.data)),
    updateIssue: (issueId: string, body: Record<string, unknown>) =>
      run(() => teamApi.patch<NishukanIssue>(`nishukan/issues/${issueId}`, body).then((r) => r.data)),
    setCheck: (issueId: string, checkId: string, done: boolean) =>
      run(() =>
        teamApi
          .post<NishukanIssue>(`nishukan/issues/${issueId}/checks/${checkId}`, { done })
          .then((r) => r.data),
      ),
    comment: (issueId: string, body: string) =>
      run(() =>
        teamApi
          .post<NishukanIssue>(`nishukan/issues/${issueId}/comments`, { body })
          .then((r) => r.data),
      ),
    holidays: (teamId: string, body: Record<string, unknown>) =>
      run(() => teamApi.post(`nishukan/teams/${teamId}/holidays`, body).then((r) => r.data)),
    receiptKey: (templateId: string) =>
      run(() =>
        teamApi
          .post<{ receiptKey: string }>(`nishukan/templates/${templateId}/receipt-key`, {})
          .then((r) => r.data),
      ),
  };
};
