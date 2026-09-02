import { ExApp } from 'genai-web';
import useSWR from 'swr';
import { isApiError, teamApiFetcher } from '@/lib/fetcher';

export const useFetchExApp = (teamId: string, exAppId: string) => {
  const { data, isLoading, error } = useSWR<ExApp>(
    teamId && exAppId ? `/teams/${teamId}/exapps/${exAppId}` : null,
    teamApiFetcher,
  );

  return {
    data,
    isLoading,
    error:
      error && isApiError(error)
        ? (error.data as { error?: string })?.error
        : JSON.stringify(error),
  };
};
