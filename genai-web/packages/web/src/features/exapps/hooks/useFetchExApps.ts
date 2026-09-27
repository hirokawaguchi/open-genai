import type { ListExAppsResponse } from 'genai-web';
import useSWR from 'swr';
import { teamApiFetcher } from '@/lib/fetcher';

export const useFetchExApps = () => {
  // Header / SideNav からも呼ぶ。suspense: true だと境界が無く画面全体が白紙になる。
  return useSWR<ListExAppsResponse>('exapps', teamApiFetcher, { suspense: false });
};
