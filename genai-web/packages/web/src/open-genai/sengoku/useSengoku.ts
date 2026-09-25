import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type { Command, GameState, SengokuConfig, TurnResult } from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useSengokuConfig = () => {
  const { data, error, isLoading } = useSWR<SengokuConfig>(
    'sengoku/config',
    async () => {
      try {
        return await teamApiFetcher<SengokuConfig>('sengoku/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as SengokuConfig | undefined;
          return {
            enabled: false,
            error: data?.error || errorMessage(e, '戦国国取りサービスに接続できません'),
          };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    config: data,
    isLoading,
    loadError: error
      ? '戦国国取りの設定取得に失敗しました。時間をおいて再度お試しください。'
      : null,
    unavailable: data?.enabled === false,
  };
};

export const useSengokuGame = () => {
  const { data, error, isLoading, mutate } = useSWR<{ game: GameState | null }>(
    'sengoku/game',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    game: data?.game ?? null,
    isLoading,
    loadError: error ? errorMessage(error, '局の読み込みに失敗しました。') : null,
    mutate,
  };
};

export const useSengokuActions = () => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startGame = useCallback(async (house: string): Promise<GameState | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await teamApi.post<{ game: GameState }>('sengoku/game', { house });
      return res.data?.game ?? null;
    } catch (e) {
      setError(errorMessage(e, '対局の開始に失敗しました。'));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const startObserver = useCallback(async (): Promise<GameState | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await teamApi.post<{ game: GameState }>('sengoku/game', {
        mode: 'observer',
      });
      return res.data?.game ?? null;
    } catch (e) {
      setError(errorMessage(e, '観戦の開始に失敗しました。'));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const abandonGame = useCallback(async (): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await teamApi.delete('sengoku/game');
      return true;
    } catch (e) {
      setError(errorMessage(e, '局の破棄に失敗しました。'));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const playTurn = useCallback(
    async (command: Command | null): Promise<TurnResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<TurnResult>('sengoku/game/turn', { command });
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'ターンの処理に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return { startGame, startObserver, abandonGame, playTurn, busy, error, setError };
};
