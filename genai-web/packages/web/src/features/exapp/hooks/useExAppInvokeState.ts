import type { GetInvokeExAppHistoryResponse, InvokeExAppRequest } from 'genai-web';
import { useEffect, useRef } from 'react';
import { useSWRConfig } from 'swr';
import { unstable_serialize } from 'swr/infinite';
import { isApiError, teamApi } from '@/lib/fetcher';
import { useExAppInvokeStore } from '../stores/useExAppInvokeStore';
import { getExAppHistoriesKey } from './useFetchInvokedExAppHistories';
import { useInvokeExApp } from './useInvokeExApp';

const HISTORY_POLL_MS = 4000;

export const useExAppInvokeState = () => {
  const { invokeExApp } = useInvokeExApp();
  const store = useExAppInvokeStore();
  const { mutate } = useSWRConfig();
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const generationRef = useRef(0);

  const stopPoll = () => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(
    () => () => {
      generationRef.current += 1;
      stopPoll();
    },
    [],
  );

  const refreshHistories = (teamId: string, exAppId: string) => {
    void mutate(unstable_serialize(getExAppHistoriesKey(teamId, exAppId)));
  };

  const pollHistory = (req: InvokeExAppRequest, createdDate: string, generation: number) => {
    stopPoll();

    const tick = async () => {
      if (generationRef.current !== generation) {
        return;
      }
      try {
        const q = new URLSearchParams({
          teamId: req.teamId,
          exAppId: req.exAppId,
          createdDate,
        }).toString();
        const res = await teamApi.get<GetInvokeExAppHistoryResponse>(
          `/exapps/history?${q}`,
        );
        const history = res.data.history;
        if (!history || generationRef.current !== generation) {
          return;
        }
        if (history.status === 'COMPLETED') {
          stopPoll();
          store.setError(null);
          store.setExAppResponse({
            outputs: history.outputs,
            artifacts: history.artifacts,
            status: 'COMPLETED',
            createdDate,
            timestamps: {
              processingStartedAt: '',
              processingEndedAt: '',
            },
          });
          refreshHistories(req.teamId, req.exAppId);
        } else if (history.status === 'ERROR') {
          stopPoll();
          store.setExAppResponse(null);
          store.setError(
            new Error(
              history.outputs?.trim() ||
                '実行中にエラーが発生しました。再度お試しください。',
            ),
          );
          refreshHistories(req.teamId, req.exAppId);
        }
      } catch {
        // 一時的な取得失敗は次の間隔でやり直す。
      }
    };

    void tick();
    timerRef.current = setInterval(() => {
      void tick();
    }, HISTORY_POLL_MS);
  };

  const invokeRequest = async (req: InvokeExAppRequest) => {
    const generation = ++generationRef.current;
    stopPoll();
    try {
      const res = await invokeExApp(req);
      if (generationRef.current !== generation) {
        return;
      }
      if (
        (res.status === 'IN_PROGRESS' || res.status === 'ACCEPTED') &&
        res.createdDate
      ) {
        store.setError(null);
        store.setExAppResponse(res);
        pollHistory(req, res.createdDate, generation);
        refreshHistories(req.teamId, req.exAppId);
        return;
      }
      store.setExAppResponse(res);
    } catch (error: unknown) {
      store.setExAppResponse(null);
      if (isApiError(error)) {
        const data = error.data as { error?: string };
        if (error.status === 413) {
          throw new Error(
            data?.error ||
              'ファイルが大きすぎます。音声はおおよそ180MBまでです。分割してから再度お試しください。',
          );
        }
        throw new Error(
          data?.error ||
            '処理中にエラーが発生しました。時間をおいて再度お試しください。解消しない場合は管理者にお問い合わせください。',
        );
      } else if (error instanceof Error) {
        throw new Error(error.message);
      }
    }
  };

  return {
    ...store,
    invokeRequest,
  };
};
