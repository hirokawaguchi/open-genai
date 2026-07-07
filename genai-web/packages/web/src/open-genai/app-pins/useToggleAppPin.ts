import { useCallback, useState } from 'react';
import { useSWRConfig } from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';
import type { AppPin, AppPinsResponse } from './types';

export const useToggleAppPin = () => {
  const { mutate } = useSWRConfig();
  const [error, setError] = useState<string | null>(null);

  const applyPins = useCallback(
    async (pins: AppPin[]) => {
      await mutate('my/app-pins', pins, { revalidate: false });
    },
    [mutate],
  );

  const pin = useCallback(
    async (teamId: string, itemId: string) => {
      setError(null);
      try {
        const res = await teamApi.post<AppPinsResponse>('my/app-pins', { teamId, itemId });
        await applyPins(res.data.pins ?? []);
        return true;
      } catch (e) {
        const message =
          e instanceof ApiError && (e.data as { error?: string })?.error
            ? (e.data as { error?: string }).error
            : 'ピン留めに失敗しました';
        setError(message ?? 'ピン留めに失敗しました');
        return false;
      }
    },
    [applyPins],
  );

  const unpin = useCallback(
    async (teamId: string, itemId: string) => {
      setError(null);
      try {
        const res = await teamApi.delete<AppPinsResponse>(
          `my/app-pins/${encodeURIComponent(teamId)}/${encodeURIComponent(itemId)}`,
        );
        await applyPins(res.data.pins ?? []);
        return true;
      } catch {
        setError('ピン留めの解除に失敗しました');
        return false;
      }
    },
    [applyPins],
  );

  return { pin, unpin, error };
};
