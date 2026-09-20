import type { RecommendedAppsResponse } from 'genai-web';
import useSWR from 'swr';
import { ApiError, teamApiFetcher } from '@/lib/fetcher';
import { ALWAYS_ON_OFFICIAL_APP_IDS, type OfficialAppsRuntime } from './runtime';

export const OFFICIAL_APPS_RUNTIME_KEY = 'official-apps/runtime';

const fetchOfficialRuntime = async (): Promise<OfficialAppsRuntime> => {
  try {
    return await teamApiFetcher<OfficialAppsRuntime>(OFFICIAL_APPS_RUNTIME_KEY);
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 404) {
      throw e;
    }
    const rec = await teamApiFetcher<RecommendedAppsResponse>('recommended-apps');
    return {
      catalog: rec.availableIds,
      running: rec.availableIds ?? [],
    };
  }
};

export const useOfficialAppRuntime = () => {
  const { data, isLoading } = useSWR<OfficialAppsRuntime>(
    OFFICIAL_APPS_RUNTIME_KEY,
    fetchOfficialRuntime,
    {
      suspense: false,
      revalidateOnFocus: false,
      refreshInterval: 60_000,
      shouldRetryOnError: false,
    },
  );
  const running = data
    ? [...new Set([...ALWAYS_ON_OFFICIAL_APP_IDS, ...data.running])]
    : undefined;
  return {
    catalog: data?.catalog,
    running,
    loaded: data !== undefined,
    isLoading,
  };
};
