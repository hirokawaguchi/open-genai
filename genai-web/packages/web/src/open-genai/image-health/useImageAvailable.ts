import useSWR from 'swr';
import { genUApiFetcher } from '@/lib/fetcher';

const fetchImageHealth = async (): Promise<{ ok: boolean }> => {
  try {
    return await genUApiFetcher<{ ok: boolean }>('image/health');
  } catch {
    return { ok: false };
  }
};

/**
 * 画像生成が利用可能かを返す（ローカル SD の到達、またはクラウド画像プロバイダの登録）。
 * 取得前（undefined）は利用可能とみなし、確定で false のときのみ非表示にする。
 */
export const useImageAvailable = (): boolean => {
  const { data } = useSWR<{ ok: boolean }>('image/health', fetchImageHealth, {
    suspense: false,
    revalidateOnFocus: false,
    refreshInterval: 60_000,
    shouldRetryOnError: false,
  });

  return data === undefined ? true : data.ok === true;
};
