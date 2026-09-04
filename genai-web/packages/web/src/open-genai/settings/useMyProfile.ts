import useSWR from 'swr';
import { teamApiFetcher } from '@/lib/fetcher';
import type { MyProfile } from './types';

/**
 * ログイン中ユーザー自身のプロフィール（姓名・表示名）を取得する。
 *
 * ヘッダー等で表示名を出すために使うため、未認証時やサービス未起動時は
 * 例外で画面を壊さないよう `enabled` で抑止し、リトライも行わない。
 */
export const useMyProfile = (enabled = true) => {
  const { data, error, isLoading, mutate } = useSWR<MyProfile>(
    enabled ? 'my/profile' : null,
    teamApiFetcher,
    {
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    },
  );
  return { profile: data, error, isLoading, mutate };
};
