import useSWR from 'swr';
import { fetchWebSearchEnabled } from '@/features/chat/webSearch';

/** Web 検索（Firecrawl Local）が使えるか。FIRECRAWL_URL 未設定なら false。 */
export const useWebSearchConfig = (): { enabled: boolean; isLoading: boolean } => {
  const { data, isLoading } = useSWR('web-search/config', fetchWebSearchEnabled, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return { enabled: !!data, isLoading };
};
