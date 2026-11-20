import type {
  GetInvokeExAppHistoryResponse,
  InvokeExAppHistory,
  InvokeExAppRequest,
  ListInvokeExAppHistoriesResponse,
} from 'genai-web';
import { useEffect, useRef } from 'react';
import { useSWRConfig } from 'swr';
import { unstable_serialize } from 'swr/infinite';
import { isApiError, teamApi } from '@/lib/fetcher';
import { useExAppInvokeStore } from '../stores/useExAppInvokeStore';
import { getExAppHistoriesKey } from './useFetchInvokedExAppHistories';
import { useInvokeExApp } from './useInvokeExApp';

const HISTORY_POLL_MS = 4000;

const missingAudioMessage = (text: string | undefined) =>
  (text ?? '').includes('ファイルが添付されていません');

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
          if (missingAudioMessage(history.outputs)) {
            store.setExAppResponse(null);
            store.setError(new Error(history.outputs.trim()));
            refreshHistories(req.teamId, req.exAppId);
            return;
          }
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

  const showHistory = (teamId: string, exAppId: string, history: InvokeExAppHistory) => {
    const generation = ++generationRef.current;
    stopPoll();
    if (history.status === 'COMPLETED') {
      if (missingAudioMessage(history.outputs)) {
        store.setExAppResponse(null);
        store.setError(new Error(history.outputs.trim()));
        return;
      }
      store.setError(null);
      store.setExAppResponse({
        outputs: history.outputs,
        artifacts: history.artifacts,
        status: 'COMPLETED',
        createdDate: history.createdDate,
        timestamps: { processingStartedAt: '', processingEndedAt: '' },
      });
      return;
    }
    if (history.status === 'ERROR') {
      store.setExAppResponse(null);
      store.setError(
        new Error(history.outputs?.trim() || '実行中にエラーが発生しました。再度お試しください。'),
      );
      return;
    }
    store.setError(null);
    store.setExAppResponse({
      outputs: history.progress || '文字起こしを実行しています。完了まで数分かかることがあります。',
      status: history.status,
      createdDate: history.createdDate,
      timestamps: { processingStartedAt: '', processingEndedAt: '' },
    });
    pollHistory({ teamId, exAppId, inputs: {} }, history.createdDate, generation);
  };

  const invokeRequest = async (req: InvokeExAppRequest) => {
    const generation = ++generationRef.current;
    stopPoll();
    try {
      const res = await invokeExApp(req);
      if (generationRef.current !== generation) {
        return undefined;
      }
      if (
        (res.status === 'IN_PROGRESS' || res.status === 'ACCEPTED') &&
        res.createdDate
      ) {
        store.setError(null);
        store.setExAppResponse(res);
        pollHistory(req, res.createdDate, generation);
        refreshHistories(req.teamId, req.exAppId);
        return res.createdDate;
      }
      store.setExAppResponse(res);
      return res.createdDate;
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

  const resumeLatest = async (teamId: string, exAppId: string) => {
    const generation = generationRef.current;
    try {
      const q = new URLSearchParams({ teamId, exAppId }).toString();
      const res = await teamApi.get<ListInvokeExAppHistoriesResponse>(`exapps/histories?${q}`);
      if (generationRef.current !== generation) {
        return;
      }
      const current = useExAppInvokeStore.getState();
      if (current.exAppResponse || current.requestLoading) {
        return;
      }
      const latest = res.data.history?.[0];
      if (!latest) {
        return;
      }
      if (latest.status === 'COMPLETED') {
        store.setError(null);
        store.setExAppResponse({
          outputs: latest.outputs,
          artifacts: latest.artifacts,
          status: 'COMPLETED',
          createdDate: latest.createdDate,
          timestamps: { processingStartedAt: '', processingEndedAt: '' },
        });
        return;
      }
      if (latest.status === 'ERROR') {
        store.setExAppResponse(null);
        store.setError(
          new Error(latest.outputs?.trim() || '実行中にエラーが発生しました。再度お試しください。'),
        );
        return;
      }
      if (latest.status === 'IN_PROGRESS' || latest.status === 'ACCEPTED') {
        store.setError(null);
        store.setExAppResponse({
          outputs: latest.progress || '文字起こしを実行しています。完了まで数分かかることがあります。',
          status: latest.status,
          createdDate: latest.createdDate,
          timestamps: { processingStartedAt: '', processingEndedAt: '' },
        });
        pollHistory({ teamId, exAppId, inputs: {} }, latest.createdDate, generation);
      }
    } catch {
      // 履歴が取れなくても、新しく実行はできる。
    }
  };

  return {
    ...store,
    invokeRequest,
    showHistory,
    resumeLatest,
  };
};
