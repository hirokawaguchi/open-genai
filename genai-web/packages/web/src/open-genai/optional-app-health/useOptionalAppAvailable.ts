import useSWR from 'swr';
import { ApiError, teamApiFetcher } from '@/lib/fetcher';

type Config = { enabled?: boolean };

const fetchConfigAvailable = async (path: string): Promise<boolean> => {
  try {
    const data = await teamApiFetcher<Config>(path);
    return data.enabled === true;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 502 || e.status === 503)) {
      return false;
    }
    return false;
  }
};

/**
 * Compose profile 任意起動アプリが利用可能か。
 * 未起動（502/503 / enabled=false）は非表示。取得前も出さない（ちらつき防止）。
 */
const useOptionalAppAvailable = (path: string): boolean => {
  const { data } = useSWR<boolean>(path, () => fetchConfigAvailable(path), {
    suspense: false,
    revalidateOnFocus: false,
    refreshInterval: 60_000,
    shouldRetryOnError: false,
  });
  return data === true;
};

export const useDoccheckAvailable = (): boolean => useOptionalAppAvailable('doccheck/config');

export const usePatchformAvailable = (): boolean => useOptionalAppAvailable('patchform/config');

export const useProcuretechAvailable = (): boolean =>
  useOptionalAppAvailable('procuretech/config');
