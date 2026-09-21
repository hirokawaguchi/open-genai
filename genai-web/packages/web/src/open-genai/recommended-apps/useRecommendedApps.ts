import type { RecommendedAppsResponse } from 'genai-web';
import useSWR, { useSWRConfig } from 'swr';
import { teamApi, teamApiFetcher } from '@/lib/fetcher';
import { RECOMMENDED_APP_OPTIONS } from './recommendedApps';

export const RECOMMENDED_APPS_KEY = 'recommended-apps';

const fallbackIds = RECOMMENDED_APP_OPTIONS.map((o) => o.id);

export const useRecommendedApps = () => {
  const { data, isLoading, error, mutate } = useSWR<RecommendedAppsResponse>(
    RECOMMENDED_APPS_KEY,
    teamApiFetcher,
    { revalidateOnFocus: false, revalidateIfStale: false },
  );
  const exAppIds = data?.exAppIds ?? fallbackIds;
  return {
    exAppIds,
    availableIds: data?.availableIds,
    isLoading,
    error,
    mutate,
    allows: (id: string) => isLoading || exAppIds.includes(id),
  };
};

export const useRecommendedAppsActions = () => {
  const { mutate } = useSWRConfig();
  return {
    save: async (exAppIds: string[]) => {
      const res = await teamApi.put<RecommendedAppsResponse>('recommended-apps', { exAppIds });
      const returned = new Set(res.data?.exAppIds ?? []);
      for (const id of exAppIds) {
        returned.add(id);
      }
      const next = RECOMMENDED_APP_OPTIONS.map((o) => o.id).filter((id) => returned.has(id));
      await mutate(
        RECOMMENDED_APPS_KEY,
        (current: RecommendedAppsResponse | undefined) => ({
          exAppIds: next,
          availableIds: res.data?.availableIds ?? current?.availableIds,
        }),
        { revalidate: false },
      );
      return { ...res.data, exAppIds: next };
    },
  };
};
