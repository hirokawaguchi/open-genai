import type { ListExAppsResponse } from 'genai-web';
import useSWR from 'swr';
import { teamApiFetcher } from '@/lib/fetcher';

/** おすすめ／組み込み一覧の表示判定用。suspense せず、未取得時は loaded=false。 */
export const useExAppCatalog = () => {
  const { data } = useSWR<ListExAppsResponse>('exapps', teamApiFetcher);
  return { apps: data ?? [], loaded: Boolean(data) };
};
