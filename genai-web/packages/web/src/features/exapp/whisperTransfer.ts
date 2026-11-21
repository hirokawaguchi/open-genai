import type { InvokeExAppResponse } from 'genai-web';
import { mutate } from 'swr';
import { unstable_serialize } from 'swr/infinite';
import { isApiError, teamApi } from '@/lib/fetcher';
import { newId } from '@/utils/uuid';
import { getExAppHistoriesKey } from './hooks/useFetchInvokedExAppHistories';
import type { WhisperDraft } from './whisperCases';
import { processFormFiles } from './utils/processFormFiles';

const draftKey = (teamId: string) => `whisper-drafts:${teamId}`;

export type WhisperTransferEvent = {
  teamId: string;
  draftId: string;
  type: 'update' | 'confirm' | 'error' | 'accepted';
  message?: string;
  createdDate?: string;
};

const running = new Set<string>();
const listeners = new Set<(event: WhisperTransferEvent) => void>();

const transferKey = (teamId: string, draftId: string) => `${teamId}:${draftId}`;

export const whisperTransferRunning = (teamId: string, draftId: string) =>
  running.has(transferKey(teamId, draftId));

export const subscribeWhisperTransfers = (listener: (event: WhisperTransferEvent) => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const emit = (event: WhisperTransferEvent) => {
  listeners.forEach((listener) => listener(event));
};

export const readWhisperDrafts = (teamId: string): WhisperDraft[] => {
  try {
    const raw = sessionStorage.getItem(draftKey(teamId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (item): item is WhisperDraft =>
        !!item &&
        typeof item === 'object' &&
        typeof (item as WhisperDraft).id === 'string' &&
        typeof (item as WhisperDraft).title === 'string',
    );
  } catch {
    return [];
  }
};

export const writeWhisperDrafts = (teamId: string, drafts: WhisperDraft[]) => {
  sessionStorage.setItem(draftKey(teamId), JSON.stringify(drafts));
};

export const upsertWhisperDraft = (teamId: string, draft: WhisperDraft) => {
  const drafts = readWhisperDrafts(teamId);
  const next = drafts.some((item) => item.id === draft.id)
    ? drafts.map((item) => (item.id === draft.id ? draft : item))
    : [draft, ...drafts];
  writeWhisperDrafts(teamId, next);
  emit({ teamId, draftId: draft.id, type: 'update' });
  return next;
};

export const removeWhisperDraft = (teamId: string, draftId: string) => {
  const next = readWhisperDrafts(teamId).filter((item) => item.id !== draftId);
  writeWhisperDrafts(teamId, next);
  emit({ teamId, draftId, type: 'update' });
  return next;
};

/** 再読込で送信処理そのものが消えた案件は、処理中のまま残さない。 */
export const settleInterruptedWhisperDrafts = (teamId: string): WhisperDraft[] => {
  const drafts = readWhisperDrafts(teamId);
  let changed = false;
  const next = drafts.map((item) => {
    if (item.phase === 'sending' && !whisperTransferRunning(teamId, item.id)) {
      changed = true;
      return {
        ...item,
        phase: 'error' as const,
        notice: '送信が中断されました。ファイルを選び直してください。',
      };
    }
    return item;
  });
  if (changed) {
    writeWhisperDrafts(teamId, next);
  }
  return next;
};

const failMessage = (error: unknown) => {
  if (isApiError(error)) {
    const data = error.data as { error?: string };
    if (error.status === 413) {
      return (
        data?.error ||
        'ファイルが大きすぎます。音声はおおよそ180MBまでです。分割してから再度お試しください。'
      );
    }
    return (
      data?.error ||
      '処理中にエラーが発生しました。時間をおいて再度お試しください。解消しない場合は管理者にお問い合わせください。'
    );
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return '文字起こしを開始できませんでした。';
};

const markDraft = (
  teamId: string,
  draftId: string,
  patch: Partial<WhisperDraft>,
  event: WhisperTransferEvent['type'],
  message?: string,
) => {
  const current = readWhisperDrafts(teamId).find((item) => item.id === draftId);
  if (!current) {
    return;
  }
  const next: WhisperDraft = { ...current, ...patch };
  if (!next.phase) {
    delete next.phase;
  }
  if (!next.notice) {
    delete next.notice;
  }
  upsertWhisperDraft(teamId, next);
  if (event !== 'update') {
    emit({ teamId, draftId, type: event, message });
  }
};

export type WhisperFileTransfer = {
  teamId: string;
  exAppId: string;
  draftId: string;
  title: string;
  createdAt: string;
  mode: 'local' | 'cloud';
  language: string;
  file: File;
  queueConfirmed: boolean;
  audioSeconds?: number | null;
};

/** 画面を閉じてもファイル送信を続け、一覧の状態を更新する。 */
export const beginWhisperFileTransfer = (input: WhisperFileTransfer) => {
  const key = transferKey(input.teamId, input.draftId);
  if (running.has(key)) {
    return;
  }
  running.add(key);
  upsertWhisperDraft(input.teamId, {
    id: input.draftId,
    title: input.title,
    createdAt: input.createdAt,
    phase: 'sending',
    mode: input.mode,
  });
  void runWhisperFileTransfer(input)
    .catch((error: unknown) => {
      markDraft(
        input.teamId,
        input.draftId,
        { phase: 'error', notice: failMessage(error) },
        'error',
        failMessage(error),
      );
    })
    .finally(() => {
      running.delete(key);
    });
};

const runWhisperFileTransfer = async (input: WhisperFileTransfer) => {
  const seconds = input.audioSeconds ?? null;
  const files = await processFormFiles({ audio: [input.file] });
  const attached = files.some((entry) => entry.files.some((item) => item.content));
  if (!attached) {
    const message = 'ファイルを読み込めませんでした。もう一度選択してください。';
    markDraft(input.teamId, input.draftId, { phase: 'error', notice: message }, 'error', message);
    return;
  }
  const body = {
    teamId: input.teamId,
    exAppId: input.exAppId,
    sessionId: newId(),
    inputs: {
      language: input.language,
      caseTitle: input.title,
      files,
      ...(seconds && seconds > 0 ? { audioSeconds: Math.round(seconds) } : {}),
      ...(input.mode === 'cloud' ? { engine: 'cloud' } : {}),
    },
  };
  const res = await teamApi.post<InvokeExAppResponse>('exapps/invoke', body);
  const created = res.data.createdDate;
  if (!created) {
    const message = '文字起こしを開始できませんでした。';
    markDraft(input.teamId, input.draftId, { phase: 'error', notice: message }, 'error', message);
    return;
  }
  removeWhisperDraft(input.teamId, input.draftId);
  void mutate(unstable_serialize(getExAppHistoriesKey(input.teamId, input.exAppId)));
  emit({ teamId: input.teamId, draftId: input.draftId, type: 'accepted', createdDate: created });
};
