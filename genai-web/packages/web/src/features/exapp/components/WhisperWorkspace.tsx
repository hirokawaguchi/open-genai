import type { ExApp, InvokeExAppHistory } from 'genai-web';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { PiBookOpenBold, PiFilePlus } from 'react-icons/pi';
import { Markdown } from '@/components/Markdown';
import { PageTitle } from '@/components/PageTitle';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { teamApi } from '@/lib/fetcher';
import { newId } from '@/utils/uuid';
import { formatDateTime } from '@/utils/formatDateTime';
import { useExAppInvokeState } from '../hooks/useExAppInvokeState';
import { useExAppInvokedHistories } from '../hooks/useExAppInvokedHistories';
import {
  defaultWhisperCaseTitle,
  whisperCaseTitle,
  whisperInputModeLabel,
  type WhisperDraft,
} from '../whisperCases';
import { availableWhisperModes, type WhisperModeId } from '../whisperModes';
import { readAudioDurationSeconds, whisperQueueParams, type WhisperQueueView } from '../whisperQueue';
import {
  beginWhisperFileTransfer,
  readWhisperDrafts,
  removeWhisperDraft,
  settleInterruptedWhisperDrafts,
  subscribeWhisperTransfers,
  upsertWhisperDraft,
} from '../whisperTransfer';
import { ExAppUsageMarkdownRenderer } from './ExAppUsageMarkdownRenderer';
import { ExAppInvokedHistoriesLoading } from './ExAppInvokedHistoriesLoading';
import { ExAppInvokedHistoryDeleteDialog } from './ExAppInvokedHistoryDeleteDialog';
import { ExAppInvokeHistoryItemStatusLabel } from './ExAppInvokeHistoryItemStatusLabel';
import { WhisperHandoff } from './WhisperHandoff';
import { WhisperLivePanel } from './WhisperLivePanel';

const ACCEPT =
  'audio/*,video/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.mp4,.webm,.opus,.wma,.aiff,.aif,.amr,.3gp,.mkv,.mov,.avi,.mpeg,.mpg';
const MAX_BYTES = 180 * 1024 * 1024;

type Props = {
  exApp: ExApp;
  pageTitle?: string;
};

export const WhisperWorkspace = (props: Props) => {
  const { exApp, pageTitle } = props;
  const [pane, setPane] = useState<'list' | 'case'>('list');
  const paneRef = useRef(pane);
  paneRef.current = pane;
  const [modes, setModes] = useState(availableWhisperModes({ cloud: false, live: false }));
  const [drafts, setDrafts] = useState<WhisperDraft[]>(() => settleInterruptedWhisperDrafts(exApp.teamId));
  const [draft, setDraft] = useState<WhisperDraft | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const [opened, setOpened] = useState<InvokeExAppHistory | null>(null);
  const [newName, setNewName] = useState('');
  const [mode, setMode] = useState<WhisperModeId>('local');
  const [language, setLanguage] = useState('auto');
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  const [queueAhead, setQueueAhead] = useState(false);
  const [checkingQueue, setCheckingQueue] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const copyRef = useRef<HTMLDivElement>(null);
  const decidedRef = useRef(false);
  const { exAppResponse, error, setError, clear, showHistory } = useExAppInvokeState();
  const showHistoryRef = useRef(showHistory);
  showHistoryRef.current = showHistory;

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      teamApi
        .get<{ cloud: boolean }>('whisper/file/config')
        .then((res) => res.data.cloud === true)
        .catch(() => false),
      teamApi
        .get<{ enabled: boolean }>('whisper/live/config')
        .then((res) => res.data.enabled === true)
        .catch(() => false),
    ]).then(([cloud, live]) => {
      if (!cancelled) {
        setModes(availableWhisperModes({ cloud, live }));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return subscribeWhisperTransfers((event) => {
      if (event.teamId !== exApp.teamId) {
        return;
      }
      const next = readWhisperDrafts(exApp.teamId);
      setDrafts(next);
      const current = draftRef.current;
      if (event.type === 'accepted' && event.createdDate && current?.id === event.draftId) {
        setDraft(null);
        setFile(null);
        setQueueAhead(false);
        if (paneRef.current === 'case') {
          const history: InvokeExAppHistory = {
            teamId: exApp.teamId,
            teamName: '',
            exAppId: exApp.exAppId,
            exAppName: exApp.exAppName,
            userId: '',
            inputs: {
              caseTitle: current.title,
              ...(current.mode === 'cloud' ? { engine: 'cloud' } : {}),
            },
            outputs: '',
            createdDate: event.createdDate,
            status: 'IN_PROGRESS',
            progress: '',
          };
          setOpened(history);
          showHistoryRef.current(exApp.teamId, exApp.exAppId, history);
        }
        return;
      }
      if (!current || current.id !== event.draftId) {
        return;
      }
      const updated = next.find((item) => item.id === current.id) ?? null;
      setDraft(updated);
      if (event.type === 'confirm') {
        setNotice(event.message ?? updated?.notice ?? '');
        setQueueAhead(true);
      } else if (event.type === 'error') {
        setNotice(event.message ?? updated?.notice ?? '');
        setQueueAhead(false);
      }
    });
  }, [exApp.exAppId, exApp.exAppName, exApp.teamId]);

  const activeMode = modes.some((item) => item.id === mode) ? mode : 'local';

  const backToList = () => {
    clear();
    setNotice('');
    setQueueAhead(false);
    setPane('list');
  };

  const openDraft = (item: WhisperDraft) => {
    clear();
    setOpened(null);
    setDraft(item);
    setFile(null);
    setNotice(item.notice ?? '');
    setQueueAhead(!!item.notice?.includes('実行しますか'));
    setLanguage('auto');
    setMode(item.mode === 'cloud' ? 'cloud' : 'local');
    setPane('case');
  };

  const openHistory = (history: InvokeExAppHistory) => {
    setDraft(null);
    setOpened(history);
    setNotice('');
    setQueueAhead(false);
    setPane('case');
    showHistory(exApp.teamId, exApp.exAppId, history);
  };

  const onFirstHistories = useCallback(
    (histories: InvokeExAppHistory[]) => {
      if (decidedRef.current || paneRef.current !== 'list') {
        return;
      }
      decidedRef.current = true;
      const running = histories.find(
        (history) => history.status === 'IN_PROGRESS' || history.status === 'ACCEPTED',
      );
      if (running) {
        setDraft(null);
        setOpened(running);
        setPane('case');
        showHistory(exApp.teamId, exApp.exAppId, running);
      }
    },
    [exApp.exAppId, exApp.teamId, showHistory],
  );

  const createCase = () => {
    const title = newName.trim() || defaultWhisperCaseTitle();
    const created: WhisperDraft = {
      id: newId(),
      title,
      createdAt: new Date().toISOString(),
    };
    upsertWhisperDraft(exApp.teamId, created);
    setNewName('');
    openDraft(created);
  };

  const renameDraft = (title: string) => {
    if (!draft || draft.phase === 'sending') {
      return;
    }
    const next = { ...draft, title };
    setDraft(next);
    upsertWhisperDraft(exApp.teamId, next);
  };

  const forgetDraft = (id: string) => {
    removeWhisperDraft(exApp.teamId, id);
    if (draft?.id === id) {
      setDraft(null);
      setPane('list');
    }
  };

  const forgetHistory = (createdDate: string) => {
    if (opened?.createdDate !== createdDate) {
      return;
    }
    setOpened(null);
    clear();
    setPane('list');
  };

  const takeFile = (next: File | null) => {
    setQueueAhead(false);
    setNotice('');
    if (next && next.size > MAX_BYTES) {
      setFile(null);
      setNotice('ファイルの目安は 180MB までです。音声トラックだけ抽出するか、ファイルを分割してから読み込んでください。');
      return;
    }
    setFile(next);
  };

  const startFile = async (queueConfirmed: boolean) => {
    const titleSource = draft?.title || (opened ? whisperCaseTitle(opened.inputs ?? {}, opened.createdDate) : '');
    if ((!draft && !opened) || !file || draft?.phase === 'sending' || checkingQueue) {
      return;
    }
    const title = titleSource.trim() || defaultWhisperCaseTitle();
    const draftId = draft?.id ?? newId();
    const createdAt = draft?.createdAt ?? new Date().toISOString();
    const fileMode = activeMode === 'cloud' ? 'cloud' : 'local';
    const chosen = file;
    setNotice('');
    setQueueAhead(false);
    setError(null);
    let seconds: number | null = null;
    if (fileMode !== 'cloud') {
      setCheckingQueue(true);
      try {
        seconds = await readAudioDurationSeconds(chosen);
        const queued = await teamApi.get<WhisperQueueView>('whisper/queue', {
          params: whisperQueueParams(chosen, seconds),
        });
        if (!queued.data.canStart) {
          const refused: WhisperDraft = {
            id: draftId,
            title,
            createdAt,
            phase: 'error',
            mode: fileMode,
            notice: queued.data.message,
          };
          setDraft(refused);
          setNotice(queued.data.message);
          upsertWhisperDraft(exApp.teamId, refused);
          return;
        }
        if (queued.data.ahead > 0 && !queueConfirmed) {
          const waiting: WhisperDraft = {
            id: draftId,
            title,
            createdAt,
            mode: fileMode,
            notice: queued.data.message,
          };
          setDraft(waiting);
          setNotice(queued.data.message);
          setQueueAhead(true);
          upsertWhisperDraft(exApp.teamId, waiting);
          return;
        }
      } catch (caught: unknown) {
        const message = caught instanceof Error ? caught.message : '待ち状況を確認できませんでした。';
        setNotice(message);
        return;
      } finally {
        setCheckingQueue(false);
      }
    }
    setDraft({
      id: draftId,
      title,
      createdAt,
      phase: 'sending',
      mode: fileMode,
    });
    beginWhisperFileTransfer({
      teamId: exApp.teamId,
      exAppId: exApp.exAppId,
      draftId,
      title,
      createdAt,
      mode: fileMode,
      language,
      file: chosen,
      queueConfirmed,
      audioSeconds: seconds,
    });
  };

  const onLiveSaved = async (createdDate: string) => {
    if (draft) {
      removeWhisperDraft(exApp.teamId, draft.id);
      setDraft(null);
    }
    const q = new URLSearchParams({
      teamId: exApp.teamId,
      exAppId: exApp.exAppId,
      createdDate,
    }).toString();
    try {
      const res = await teamApi.get<{ history: InvokeExAppHistory | null }>(`/exapps/history?${q}`);
      if (res.data.history) {
        openHistory(res.data.history);
      }
    } catch {
      setNotice('結果の読み込みに失敗しました。案件一覧から開き直してください。');
    }
  };

  const retry = () => {
    const title = opened ? whisperCaseTitle(opened.inputs ?? {}, opened.createdDate) : defaultWhisperCaseTitle();
    const created: WhisperDraft = { id: newId(), title, createdAt: new Date().toISOString() };
    upsertWhisperDraft(exApp.teamId, created);
    openDraft(created);
  };

  const sendingFile = draft?.phase === 'sending';
  const waiting =
    sendingFile ||
    exAppResponse?.status === 'IN_PROGRESS' ||
    exAppResponse?.status === 'ACCEPTED';
  const transcript = (!waiting && !error ? (exAppResponse?.outputs ?? '') : '').replace(
    '**音声の送信先**: OpenAI（gpt-live-transcribe）',
    '**音声の送信先**: クラウドAI（海外リージョン）',
  );
  const recoverFile = !!opened && !draft && !!error && error.includes('ファイルが添付されていません');
  const showFileIntake = ((!!draft && draft.phase !== 'sending') || recoverFile) && activeMode !== 'live';
  const caseTitle = draft?.title || (opened ? whisperCaseTitle(opened.inputs ?? {}, opened.createdDate) : '');

  return (
    <div className='mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) flex-col overflow-hidden px-4 py-2 lg:px-6'>
      <PageTitle title={pageTitle} />
      {pane === 'list' ? (
        <div className='min-h-0 flex-1 overflow-y-auto'>
          <div className='mb-3 flex flex-col gap-3'>
            <BreadcrumbsNav
              items={[
                { label: 'ホーム', to: '/' },
                { label: 'AIアプリ', to: '/apps' },
                { label: exApp.exAppName },
              ]}
            />
            <h1 className='text-std-20B-160 lg:text-std-24B-150'>{exApp.exAppName}</h1>
            {exApp.description ? (
              <p className='text-std-16N-170 text-solid-gray-700'>{exApp.description}</p>
            ) : null}
            <div className='flex justify-end'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                className='inline-flex items-center gap-1'
                onClick={() => setHelpOpen(true)}
              >
                <PiBookOpenBold aria-hidden={true} className='size-4' />
                使い方
              </Button>
            </div>
          </div>
          <Suspense fallback={<ExAppInvokedHistoriesLoading />}>
            <WhisperCaseList
              exApp={exApp}
              drafts={drafts}
              newName={newName}
              onName={setNewName}
              onCreate={createCase}
              onOpenDraft={openDraft}
              onOpenHistory={openHistory}
              onDeleteDraft={forgetDraft}
              onDeleteHistory={forgetHistory}
              onFirstHistories={onFirstHistories}
            />
          </Suspense>
        </div>
      ) : (
        <div className='flex min-h-0 flex-1 flex-col gap-3'>
          <div className='flex min-w-0 items-center justify-between gap-3'>
            <div className='flex min-w-0 items-baseline gap-3'>
              <Button type='button' variant='outline' size='sm' onClick={backToList}>
                一覧へ戻る
              </Button>
              <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{exApp.exAppName}</h1>
              {exApp.description ? (
                <p className='truncate text-dns-14N-130 text-solid-gray-600' title={exApp.description}>
                  {exApp.description}
                </p>
              ) : null}
            </div>
            <Button
              type='button'
              variant='outline'
              size='sm'
              className='inline-flex shrink-0 items-center gap-1'
              onClick={() => setHelpOpen(true)}
            >
              <PiBookOpenBold aria-hidden={true} className='size-4' />
              使い方
            </Button>
          </div>
          {!draft && !opened ? (
            <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
              「案件一覧」から案件を開いてください。
            </div>
          ) : (
            <div className='flex min-h-0 flex-1 flex-col gap-3'>
              <div className='flex flex-wrap items-center gap-2 rounded-8 border border-solid-gray-300 px-3 py-2'>
                {draft ? (
                  <label className='flex min-w-0 flex-1 flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                    案件名
                    <Input
                      id='whisper-case-title'
                      blockSize='sm'
                      value={draft.title}
                      onChange={(event) => renameDraft(event.target.value)}
                    />
                  </label>
                ) : (
                  <h2 className='min-w-0 flex-1 truncate text-std-16B-150 text-solid-gray-900'>{caseTitle}</h2>
                )}
                {opened ? (
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    {whisperInputModeLabel(opened.inputs ?? {})}
                  </p>
                ) : null}
              </div>
              {(draft || recoverFile) && draft?.phase !== 'sending' && modes.length > 1 ? (
                <div className='flex flex-wrap gap-1 border-b border-solid-gray-300' role='radiogroup' aria-label='方式'>
                  {modes.map((item) => (
                    <button
                      key={item.id}
                      type='button'
                      role='radio'
                      aria-checked={activeMode === item.id}
                      className={
                        activeMode === item.id
                          ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                          : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900'
                      }
                      onClick={() => {
                        setMode(item.id);
                        setQueueAhead(false);
                        setNotice('');
                      }}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              ) : null}
              {(draft || recoverFile) && draft?.phase !== 'sending' && activeMode === 'cloud' ? (
                <SupportText>この方式では、読み込んだ音声をクラウドAI（海外リージョン）へ送信します。</SupportText>
              ) : null}
              {notice ? <ErrorText>＊{notice}</ErrorText> : null}
              {(draft || recoverFile) && activeMode === 'live' ? (
                <div className='flex min-h-0 flex-1 flex-col gap-3'>
                  <label className='flex w-48 flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                    言語
                    <Select
                      id='whisper-case-language'
                      blockSize='sm'
                      value={language}
                      onChange={(event) => setLanguage(event.target.value)}
                    >
                      <option value='auto'>自動判定</option>
                      <option value='ja'>日本語</option>
                      <option value='en'>英語</option>
                    </Select>
                  </label>
                  <WhisperLivePanel
                    teamId={exApp.teamId}
                    exAppId={exApp.exAppId}
                    shown
                    embedded
                    language={language}
                    caseTitle={draft?.title || caseTitle}
                    onSaved={(createdDate) => void onLiveSaved(createdDate)}
                  />
                </div>
              ) : null}
              {waiting ? (
                <div
                  className='flex min-h-48 flex-1 flex-col items-center justify-center rounded-8 border border-solid-gray-300 bg-white'
                  role='status'
                >
                  <ProgressIndicator
                    isLarge
                    label={
                      sendingFile
                        ? 'ファイルを送信しています'
                        : exAppResponse?.outputs ||
                          '文字起こしを実行しています。完了まで数分かかることがあります。'
                    }
                  />
                </div>
              ) : null}
              {showFileIntake && !waiting ? (
                <div className='flex min-h-0 flex-1 flex-col gap-3'>
                  <div
                    className={`flex min-h-48 flex-1 flex-col items-center justify-center gap-3 rounded-8 border border-dashed px-6 py-8 text-center ${
                      dragging ? 'border-blue-900 bg-blue-50' : 'border-solid-gray-420 bg-solid-gray-50'
                    }`}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(event) => {
                      event.preventDefault();
                      setDragging(false);
                      takeFile(event.dataTransfer.files?.[0] ?? null);
                    }}
                  >
                    <p className='text-std-16B-150 text-solid-gray-900'>
                      {file
                        ? file.name
                        : recoverFile
                          ? '前回は選んだファイルが届きませんでした。ここに入れ直してください'
                          : '音声または動画を、この枠へドロップ'}
                    </p>
                    <p className='max-w-xl text-dns-14N-130 text-solid-gray-600'>
                      mp3 / wav / m4a / mp4 / webm など。目安 180MB まで。対応形式は使い方を参照してください。
                    </p>
                    <input
                      ref={fileRef}
                      type='file'
                      accept={ACCEPT}
                      className='sr-only'
                      onChange={(event) => {
                        takeFile(event.target.files?.[0] ?? null);
                        event.target.value = '';
                      }}
                    />
                    <Button type='button' variant='outline' size='sm' onClick={() => fileRef.current?.click()}>
                      ファイルを選択
                    </Button>
                  </div>
                  <div className='flex flex-wrap items-end justify-between gap-3'>
                    <label className='flex w-48 flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                      言語
                      <Select
                        id='whisper-file-language'
                        blockSize='sm'
                        value={language}
                        onChange={(event) => setLanguage(event.target.value)}
                      >
                        <option value='auto'>自動判定</option>
                        <option value='ja'>日本語</option>
                        <option value='en'>英語</option>
                      </Select>
                    </label>
                    <div className='flex flex-wrap items-center gap-2'>
                      {queueAhead ? (
                        <Button
                          type='button'
                          variant='solid-fill'
                          size='md'
                          aria-disabled={checkingQueue ? true : undefined}
                          onClick={() => {
                            if (checkingQueue) {
                              return;
                            }
                            void startFile(true);
                          }}
                        >
                          {checkingQueue ? '待ちを確認しています' : '待ちに加える'}
                        </Button>
                      ) : (
                        <Button
                          type='button'
                          variant='solid-fill'
                          size='md'
                          aria-disabled={!file || checkingQueue ? true : undefined}
                          onClick={() => {
                            if (!file || checkingQueue) {
                              return;
                            }
                            void startFile(false);
                          }}
                        >
                          {checkingQueue ? '待ちを確認しています' : '文字起こしを開始'}
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              ) : null}
              {opened && !recoverFile && !waiting ? (
                <article className='min-h-0 flex-1 overflow-y-auto rounded-8 border border-solid-gray-300 bg-white p-4'>
                  {error ? <p className='text-error-1'>{error}</p> : null}
                  {transcript ? (
                    <>
                      <div ref={copyRef}>
                        <Markdown>{transcript}</Markdown>
                      </div>
                      <div className='mt-4 flex flex-wrap items-center justify-end gap-2'>
                        <WhisperHandoff text={transcript} />
                        <ButtonCopy text={transcript} targetRef={copyRef} />
                      </div>
                    </>
                  ) : null}
                  {error ? (
                    <div className='mt-4'>
                      <Button type='button' variant='outline' size='sm' onClick={retry}>
                        同じ名前でやり直す
                      </Button>
                    </div>
                  ) : null}
                </article>
              ) : null}
            </div>
          )}
        </div>
      )}
      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            {exApp.howToUse ? (
              <ExAppUsageMarkdownRenderer content={exApp.howToUse} size='sm' />
            ) : (
              <p className='text-std-16N-170 text-solid-gray-700'>
                案件を作成し、方式を選んで音声を読み込みます。
              </p>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </div>
  );
};

const WhisperCaseList = (props: {
  exApp: ExApp;
  drafts: WhisperDraft[];
  newName: string;
  onName: (value: string) => void;
  onCreate: () => void;
  onOpenDraft: (draft: WhisperDraft) => void;
  onOpenHistory: (history: InvokeExAppHistory) => void;
  onDeleteDraft: (id: string) => void;
  onDeleteHistory: (createdDate: string) => void;
  onFirstHistories: (histories: InvokeExAppHistory[]) => void;
}) => {
  const { histories, hasMore, loadMore, mutate } = useExAppInvokedHistories(
    props.exApp.teamId,
    props.exApp.exAppId,
  );
  const [deleting, setDeleting] = useState<InvokeExAppHistory | null>(null);
  const ime = useRef(false);
  const told = useRef(false);
  const hasPending = histories.some(
    (history) => history.status === 'IN_PROGRESS' || history.status === 'ACCEPTED',
  );

  useEffect(() => {
    if (told.current) {
      return;
    }
    told.current = true;
    props.onFirstHistories(histories);
  }, [histories, props]);

  const sending = props.drafts.some((item) => item.phase === 'sending');
  useEffect(() => {
    if (!hasPending && !sending) {
      return;
    }
    const id = window.setInterval(() => {
      void mutate();
    }, 4000);
    return () => window.clearInterval(id);
  }, [hasPending, sending, mutate]);

  const rows = [
    ...props.drafts.map((item) => ({
      kind: 'draft' as const,
      id: item.id,
      title: item.title || '無題',
      mode: item.mode ? whisperInputModeLabel(item.mode === 'cloud' ? { engine: 'cloud' } : {}) : '—',
      at: Date.parse(item.createdAt) || 0,
      draft: item,
    })),
    ...histories.map((history) => ({
      kind: 'history' as const,
      id: history.createdDate,
      title: whisperCaseTitle(history.inputs ?? {}, history.createdDate),
      mode: whisperInputModeLabel(history.inputs ?? {}),
      at: Number(history.createdDate) || 0,
      history,
    })),
  ].sort((a, b) => b.at - a.at);

  return (
    <section className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-end justify-between gap-2'>
        <h2 className='text-std-18B-160 text-solid-gray-900'>案件一覧</h2>
        <div className='flex flex-wrap items-end gap-2'>
          <label htmlFor='whisper-new-name' className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
            新規案件名
            <Input
              id='whisper-new-name'
              blockSize='sm'
              value={props.newName}
              onChange={(event) => props.onName(event.target.value)}
              placeholder={defaultWhisperCaseTitle()}
              className='w-64'
              onCompositionStart={() => {
                ime.current = true;
              }}
              onCompositionEnd={() => {
                window.setTimeout(() => {
                  ime.current = false;
                }, 100);
              }}
              onKeyDown={(event) => {
                const native = event.nativeEvent;
                if (native.isComposing || native.keyCode === 229 || ime.current) {
                  return;
                }
                if (event.key === 'Enter') {
                  event.preventDefault();
                  props.onCreate();
                }
              }}
            />
          </label>
          <Button type='button' variant='solid-fill' size='sm' onClick={props.onCreate}>
            <span className='inline-flex items-center gap-1 whitespace-nowrap'>
              <PiFilePlus className='size-4' aria-hidden={true} />
              作成
            </span>
          </Button>
        </div>
      </div>
      <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
        <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
          <thead>
            <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
              <th className='px-3 py-2'>案件名</th>
              <th className='px-3 py-2'>方式</th>
              <th className='px-3 py-2'>状態</th>
              <th className='px-3 py-2'>日時</th>
              <th className='px-3 py-2 text-right'>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className='px-3 py-6 text-center text-solid-gray-500'>
                  案件がありません。右上から作成してください。
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={`${row.kind}-${row.id}`} className='border-b border-solid-gray-200 last:border-b-0'>
                  <td className='max-w-[24rem] px-3 py-2 break-all text-solid-gray-900'>{row.title}</td>
                  <td className='px-3 py-2 text-solid-gray-700'>{row.mode}</td>
                  <td className='px-3 py-2'>
                    {row.kind === 'draft' && row.draft.phase === 'sending' ? (
                      <span className='inline-flex items-center gap-2'>
                        <ProgressIndicator label='処理中' />
                      </span>
                    ) : row.kind === 'draft' && row.draft.phase === 'error' ? (
                      <span className='inline-flex rounded-full bg-error-2 px-2 py-0.5 text-white'>エラー</span>
                    ) : row.kind === 'draft' ? (
                      <span className='inline-flex rounded-full border border-solid-gray-420 px-2 py-0.5 text-solid-gray-700'>
                        未着手
                      </span>
                    ) : row.history.status === 'IN_PROGRESS' || row.history.status === 'ACCEPTED' ? (
                      <span className='inline-flex items-center gap-2'>
                        <ProgressIndicator label='処理中' />
                      </span>
                    ) : (
                      <ExAppInvokeHistoryItemStatusLabel status={row.history.status} />
                    )}
                  </td>
                  <td className='px-3 py-2 whitespace-nowrap text-solid-gray-600'>
                    {row.kind === 'history' ? formatDateTime(row.history.createdDate) : formatDateTime(row.at)}
                  </td>
                  <td className='px-3 py-2 text-right'>
                    <div className='inline-flex gap-2'>
                      <Button
                        type='button'
                        variant='solid-fill'
                        size='xs'
                        onClick={() =>
                          row.kind === 'draft' ? props.onOpenDraft(row.draft) : props.onOpenHistory(row.history)
                        }
                      >
                        開く
                      </Button>
                      <Button
                        type='button'
                        variant='outline'
                        size='xs'
                        aria-disabled={row.kind === 'draft' && row.draft.phase === 'sending' ? true : undefined}
                        onClick={() => {
                          if (row.kind === 'draft' && row.draft.phase === 'sending') {
                            return;
                          }
                          if (row.kind === 'draft') {
                            props.onDeleteDraft(row.draft.id);
                            return;
                          }
                          setDeleting(row.history);
                        }}
                      >
                        削除
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {hasMore ? (
        <Button type='button' variant='outline' size='sm' className='self-center' onClick={loadMore}>
          さらに読み込む
        </Button>
      ) : null}
      {deleting ? (
        <ExAppInvokedHistoryDeleteDialog
          history={deleting}
          isOpen
          setIsOpen={(open) => {
            if (!open) {
              setDeleting(null);
            }
          }}
          onDeleted={() => {
            const createdDate = deleting.createdDate;
            setDeleting(null);
            props.onDeleteHistory(createdDate);
            void mutate();
          }}
        />
      ) : null}
    </section>
  );
};
