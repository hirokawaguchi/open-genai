import { useEffect, useRef, type RefObject } from 'react';
import { PiSpinnerGap } from 'react-icons/pi';
import { latexToPlain } from '@/components/latexToPlain';
import { saveDiagramFiles, saveGeneratedImage } from './notebookMedia';
import { sourceFilename } from './NotebookSourceHandoff';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { SupportText } from '@/components/ui/dads/SupportText';
import { AttachmentIcon } from '@/components/ui/icons/AttachmentIcon';
import { ClipIcon } from '@/components/ui/icons/ClipIcon';
import { ReplayIcon } from '@/components/ui/icons/ReplayIcon';
import { SearchIcon } from '@/components/ui/icons/SearchIcon';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { Switch } from '@/components/ui/Switch';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { DiagramSupplement } from '@/features/chat/components/DiagramSupplement';
import { ExportAnswerPowerPoint } from '@/features/chat/components/ExportAnswerPowerPoint';
import { ExportAnswerWord } from '@/features/chat/components/ExportAnswerWord';
import { ImageSupplement } from '@/features/chat/components/ImageSupplement';
import { teamApi } from '@/lib/fetcher';
import { useSubmitKey } from '@/hooks/useSubmitKey';
import { requestSubmitOnEnter } from '@/utils/keyboard';
import { ChatAnswer } from './Citations';
import { notebookToolName, toolLabel } from './toolLabels';
import type { NotebookMessage, NotebookSchedule, NotebookToolTrace } from './types';

export type ManuscriptPlace = {
  projectId: string;
  projectName: string;
  fileName: string;
};

type Props = {
  messages: NotebookMessage[];
  draft: string;
  manuscriptPlace?: ManuscriptPlace | null;
  onOpenManuscript?: () => void;
  officeFile?: string;
  officeAttempted?: boolean;
  officeCompose?: 'pptx' | 'docx' | '';
  onOpenOffice?: () => void;
  submitting: boolean;
  liveSteps?: string[];
  llmEnabled: boolean;
  attaching: boolean;
  knowledgeBusy: boolean;
  uploadLimitMb: number;
  notice?: string | null;
  readingLabel?: string;
  webSearchOn: boolean;
  webSearchAvailable: boolean;
  onWebSearch: (next: boolean) => void;
  onAttach: () => void;
  onOpenKnowledge: () => void;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  sessionId: string | null;
  onRetry: () => void;
  onClip: (messageId: string) => void;
  clippedMessageIds?: string[];
  sourceNames?: string[];
  onSourcesChanged?: () => void;
  schedule?: NotebookSchedule | null;
  scheduleBusy?: boolean;
  scheduleError?: string;
  onConfirmSchedule?: () => void;
  onDismissSchedule?: () => void;
  onOpenSchedule?: () => void;
};

const formatScheduleWhen = (value: string, allDay?: boolean) => {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replace(/-/g, '/');
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    ...(allDay ? {} : { hour: 'numeric', minute: '2-digit' }),
  }).format(date);
};

const proposedOn = (message: NotebookMessage) =>
  (message.tool_trace ?? []).some((trace) => notebookToolName(trace.name) === 'propose_schedule');

const ScheduleNote = ({
  schedule,
  busy,
  error,
  onConfirm,
  onDismiss,
  onOpen,
}: {
  schedule: NotebookSchedule;
  busy?: boolean;
  error?: string;
  onConfirm?: () => void;
  onDismiss?: () => void;
  onOpen?: () => void;
}) => (
  <div className='mt-3 rounded-8 border border-solid-gray-420 bg-solid-gray-50 p-3'>
    <p className='text-std-16N-170 text-solid-gray-800'>
      {schedule.status === 'created'
        ? `日程調整の案件「${schedule.title}」を作りました。招待は送っていません。`
        : `この内容で日程調整の案件を作れます。「${schedule.title}」`}
    </p>
    {schedule.description ? (
      <p className='mt-2 whitespace-pre-wrap text-dns-14N-130 text-solid-gray-700'>
        {schedule.description}
      </p>
    ) : null}
    <ul className='mt-2 list-disc pl-5 text-dns-14N-130 text-solid-gray-800'>
      {schedule.dates.map((date) => (
        <li key={`${date.start_time}-${date.end_time ?? ''}`}>
          {formatScheduleWhen(date.start_time, date.is_all_day)}
          {date.end_time ? ` 〜 ${formatScheduleWhen(date.end_time)}` : ''}
          {date.is_all_day ? '（終日）' : ''}
        </li>
      ))}
    </ul>
    {error ? <p className='mt-2 text-dns-14N-130 text-error-1'>{error}</p> : null}
    <div className='mt-3 flex flex-wrap gap-2'>
      {schedule.status === 'created' && onOpen ? (
        <Button type='button' variant='solid-fill' size='sm' onClick={onOpen}>
          案件を開く
        </Button>
      ) : null}
      {schedule.status === 'proposed' ? (
        <>
          <Button
            type='button'
            variant='solid-fill'
            size='sm'
            aria-disabled={busy || undefined}
            onClick={() => onConfirm?.()}
          >
            {busy ? '作っています...' : 'この内容で案件を作る'}
          </Button>
          <Button
            type='button'
            variant='outline'
            size='sm'
            aria-disabled={busy || undefined}
            onClick={() => onDismiss?.()}
          >
            やめる
          </Button>
        </>
      ) : null}
    </div>
  </div>
);

const stepTraces = (names: string[]): NotebookToolTrace[] =>
  names.map((name) => ({ name }));

const ThinkingLine = ({ steps }: { steps: string[] }) => {
  const latest = [...steps].reverse().map((name) => toolLabel(name)).find(Boolean) ?? '';
  const text = latest ? `考えています · ${latest}` : '考えています';
  return (
    <div className='flex items-center gap-2 px-1 py-1' role='status' aria-live='polite'>
      <span
        className='inline-block size-3 shrink-0 animate-spin rounded-full border-2 border-solid-gray-300 border-t-solid-gray-536'
        aria-hidden={true}
      />
      <p className='min-w-0 truncate text-dns-14N-130 text-solid-gray-536'>{text}</p>
    </div>
  );
};

const visibleSteps = (traces?: NotebookToolTrace[]) => {
  const steps: NotebookToolTrace[] = [];
  let previous = '';
  for (const trace of traces ?? []) {
    const label = toolLabel(trace.name);
    if (!label || label === previous) continue;
    previous = label;
    steps.push(trace);
  }
  return steps;
};

const AnswerActions = ({
  sessionId,
  message,
  allowRetry,
  onRetry,
  onClip,
  clipped,
  copyRef,
  sourceNames,
  onSourcesChanged,
}: {
  sessionId: string | null;
  message: NotebookMessage;
  allowRetry: boolean;
  onRetry: () => void;
  onClip: (messageId: string) => void;
  clipped: boolean;
  copyRef: RefObject<HTMLDivElement | null>;
  sourceNames: string[];
  onSourcesChanged?: () => void;
}) => {
  const kept = useRef(new Set<string>());
  const text = message.content.trim();
  if (!text || !sessionId || message.id.startsWith('local-')) return null;
  const plain = latexToPlain(message.content);
  const remember = async (key: string, name: string, save: () => Promise<string | null>) => {
    if (kept.current.has(key) || sourceNames.includes(name)) return;
    kept.current.add(key);
    const failed = await save();
    if (failed) {
      kept.current.delete(key);
      return;
    }
    onSourcesChanged?.();
  };
  const loadDiagram = () =>
    teamApi
      .post<{ status: 'none' | 'ready'; mermaid?: string }>(
        `notebook/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(message.id)}/diagram`,
        {},
      )
      .then(async (res) => {
        const code = res.data.mermaid?.trim() ?? '';
        if (res.data.status === 'ready' && code) {
          const name = sourceFilename('図.md', message.content);
          await remember(`diagram:${message.id}`, name, () =>
            saveDiagramFiles(sessionId, message.content, code),
          );
        }
        return res.data;
      });
  const loadImage = () =>
    teamApi
      .post<{ status: 'none' | 'ready'; image?: string }>(
        `notebook/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(message.id)}/image`,
        {},
      )
      .then(async (res) => {
        const image = res.data.image ?? '';
        if (res.data.status === 'ready' && image) {
          const name = sourceFilename('画像.png', message.content);
          await remember(`image:${message.id}`, name, () =>
            saveGeneratedImage(sessionId, message.content, image),
          );
        }
        return res.data;
      });
  return (
    <div className='mt-1 flex flex-wrap items-center justify-end gap-x-1 gap-y-1 print:hidden [&_button]:shrink-0 [&_button]:whitespace-nowrap'>
      <DiagramSupplement
        chatId={sessionId}
        messageId={message.id}
        content={message.content}
        load={loadDiagram}
      />
      <ImageSupplement
        chatId={sessionId}
        messageId={message.id}
        content={message.content}
        load={loadImage}
      />
      {allowRetry && (
        <Button
          variant='text'
          size='sm'
          className='inline-flex items-center justify-center gap-x-1'
          onClick={onRetry}
        >
          <ReplayIcon className='shrink-0' aria-hidden={true} />
          再生成
        </Button>
      )}
      <ButtonCopy className='mr-0.5' text={plain} targetRef={copyRef} />
      <ExportAnswerWord text={plain} targetRef={copyRef} />
      <ExportAnswerPowerPoint text={plain} />
      <Button
        variant='text'
        size='sm'
        className='inline-flex items-center justify-center gap-x-1'
        onClick={() => onClip(message.id)}
      >
        <ClipIcon className='shrink-0' aria-hidden={true} />
        {clipped ? 'クリップ済み' : 'クリップ'}
      </Button>
    </div>
  );
};

const ManuscriptNote = ({
  place,
  onOpen,
  officeFile,
  officeAttempted,
  officeCompose,
  onOpenOffice,
}: {
  place: ManuscriptPlace;
  onOpen: () => void;
  officeFile?: string;
  officeAttempted?: boolean;
  officeCompose?: 'pptx' | 'docx' | '';
  onOpenOffice?: () => void;
}) => (
  <div className='mt-3 rounded-8 border border-solid-gray-420 bg-solid-gray-50 p-3'>
    <p className='text-std-16N-170 text-solid-gray-800'>
      原稿は Markdown エディタのプロジェクト「{place.projectName}」に、「{place.fileName}」として書き出しています。前のファイルは残します。
    </p>
    <p className='mt-2 text-dns-14N-130 text-solid-gray-700'>
      開くときは、左のメニューで Markdown エディタを選び、プロジェクト「{place.projectName}」を開いて「
      {place.fileName}」を選んでください。
    </p>
    {officeFile ? (
      <p className='mt-2 text-dns-14N-130 text-solid-gray-700'>
        文書台帳の下書きに「{officeFile}」を置きました。台帳の「文書」を開き、そのファイル名を選んでください。
      </p>
    ) : officeCompose === 'pptx' ? (
      <p className='mt-2 text-dns-14N-130 text-solid-gray-700'>
        見出しごとの原稿をそのままスライドにし、文書台帳の下書きに置きます。
      </p>
    ) : officeCompose === 'docx' ? (
      <p className='mt-2 text-dns-14N-130 text-solid-gray-700'>
        原稿を文書にし、文書台帳の下書きに置きます。
      </p>
    ) : officeAttempted ? (
      <p className='mt-2 text-dns-14N-130 text-solid-gray-700'>文書台帳には保存できていません。</p>
    ) : null}
    <div className='mt-3 flex flex-wrap gap-2'>
      <Button type='button' variant='outline' size='md' onClick={onOpen}>
        {place.fileName} を開く
      </Button>
      {officeFile && onOpenOffice ? (
        <Button type='button' variant='outline' size='md' onClick={onOpenOffice}>
          {officeFile} を開く
        </Button>
      ) : null}
    </div>
  </div>
);

const AssistantTurn = ({
  message,
  sessionId,
  pending,
  liveSteps,
  allowRetry,
  onRetry,
  onClip,
  clipped,
  manuscriptPlace,
  onOpenManuscript,
  officeFile,
  officeAttempted,
  officeCompose,
  onOpenOffice,
  sourceNames,
  onSourcesChanged,
  schedule,
  scheduleBusy,
  scheduleError,
  onConfirmSchedule,
  onDismissSchedule,
  onOpenSchedule,
}: {
  message: NotebookMessage;
  sessionId: string | null;
  pending: boolean;
  liveSteps: string[];
  allowRetry: boolean;
  onRetry: () => void;
  onClip: (messageId: string) => void;
  clipped: boolean;
  manuscriptPlace?: ManuscriptPlace | null;
  onOpenManuscript?: () => void;
  officeFile?: string;
  officeAttempted?: boolean;
  officeCompose?: 'pptx' | 'docx' | '';
  onOpenOffice?: () => void;
  sourceNames: string[];
  onSourcesChanged?: () => void;
  schedule?: NotebookSchedule | null;
  scheduleBusy?: boolean;
  scheduleError?: string;
  onConfirmSchedule?: () => void;
  onDismissSchedule?: () => void;
  onOpenSchedule?: () => void;
}) => {
  const copyRef = useRef<HTMLDivElement>(null);
  const traces = pending && liveSteps.length ? stepTraces(liveSteps) : message.tool_trace;
  return (
    <article className='rounded-12 border border-solid-gray-420 bg-white p-4 lg:px-6'>
      <h2 className='sr-only'>AIの回答</h2>
      <AgentSteps traces={traces} />
      {!pending && (
        <div ref={copyRef}>
          <ChatAnswer
            content={message.content}
            citations={message.citations ?? []}
            idPrefix={`nb-cite-${message.id}`}
          />
          {manuscriptPlace && onOpenManuscript && (
            <ManuscriptNote
              place={manuscriptPlace}
              onOpen={onOpenManuscript}
              officeFile={officeFile}
              officeAttempted={officeAttempted}
              officeCompose={officeCompose}
              onOpenOffice={onOpenOffice}
            />
          )}
          {schedule ? (
            <ScheduleNote
              schedule={schedule}
              busy={scheduleBusy}
              error={scheduleError}
              onConfirm={onConfirmSchedule}
              onDismiss={onDismissSchedule}
              onOpen={onOpenSchedule}
            />
          ) : null}
        </div>
      )}
      {pending && <ThinkingLine steps={liveSteps} />}
      {!pending && (
        <AnswerActions
          sessionId={sessionId}
          message={message}
          allowRetry={allowRetry}
          onRetry={onRetry}
          onClip={onClip}
          clipped={clipped}
          copyRef={copyRef}
          sourceNames={sourceNames}
          onSourcesChanged={onSourcesChanged}
        />
      )}
    </article>
  );
};

const AgentSteps = ({ traces }: { traces?: NotebookToolTrace[] }) => {
  const steps = visibleSteps(traces);
  if (!steps.length) return null;
  return (
    <Disclosure className='mb-2'>
      <DisclosureSummary className='text-dns-14N-130 text-solid-gray-700'>
        調べた手順
      </DisclosureSummary>
      <ol className='mt-2 list-decimal rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-3 py-2 pl-7 text-dns-14N-130 text-solid-gray-800'>
        {steps.map((trace, i) => (
          <li key={`${trace.name}-${i}`} className='py-0.5'>
            <span className='text-std-16B-150'>{toolLabel(trace.name)}</span>
          </li>
        ))}
      </ol>
    </Disclosure>
  );
};

export const NotebookChat = ({
  messages,
  draft,
  submitting,
  liveSteps = [],
  llmEnabled,
  attaching,
  knowledgeBusy,
  uploadLimitMb,
  notice,
  readingLabel = '',
  webSearchOn,
  webSearchAvailable,
  onWebSearch,
  onAttach,
  onOpenKnowledge,
  onDraftChange,
  onSend,
  sessionId,
  onRetry,
  onClip,
  clippedMessageIds = [],
  manuscriptPlace = null,
  onOpenManuscript,
  officeFile,
  officeAttempted,
  officeCompose,
  onOpenOffice,
  sourceNames = [],
  onSourcesChanged,
  schedule = null,
  scheduleBusy = false,
  scheduleError = '',
  onConfirmSchedule,
  onDismissSchedule,
  onOpenSchedule,
}: Props) => {
  const { hint } = useSubmitKey();
  const listRef = useRef<HTMLDivElement>(null);
  const empty = messages.length === 0 && !submitting;
  const lastMessage = messages[messages.length - 1];
  const lastKey = lastMessage?.id ?? '';
  const lastText = lastMessage?.content ?? '';

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const id = window.requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
    return () => window.cancelAnimationFrame(id);
  }, [lastKey, lastText, liveSteps.join('\n'), messages.length, submitting]);

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div
        ref={listRef}
        className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain py-3'
      >
        {empty && (
          <p className='text-std-16N-170 text-solid-gray-536'>
            メッセージを入力して会話を始めましょう。調べた手順は回答の上に出ます。
          </p>
        )}
        {messages.map((m, index) => {
          const latest = index === messages.length - 1;
          const pending = submitting && latest && m.role === 'assistant';
          const showManuscript =
            !pending &&
            m.open_editor &&
            Boolean(manuscriptPlace) &&
            !messages.slice(index + 1).some((later) => later.role === 'assistant' && later.open_editor);
          return m.role === 'assistant' ? (
            <AssistantTurn
              key={m.id}
              message={m}
              sessionId={sessionId}
              pending={pending}
              liveSteps={pending ? liveSteps : []}
              allowRetry={latest && !submitting}
              onRetry={onRetry}
              onClip={onClip}
              clipped={clippedMessageIds.includes(m.id)}
              manuscriptPlace={showManuscript ? manuscriptPlace : null}
              onOpenManuscript={onOpenManuscript}
              officeFile={showManuscript ? officeFile : undefined}
              officeAttempted={showManuscript ? officeAttempted : false}
              officeCompose={showManuscript ? officeCompose : ''}
              onOpenOffice={showManuscript ? onOpenOffice : undefined}
              sourceNames={sourceNames}
              onSourcesChanged={onSourcesChanged}
              schedule={
                !pending &&
                schedule &&
                proposedOn(m) &&
                !messages.slice(index + 1).some((later) => proposedOn(later))
                  ? schedule
                  : null
              }
              scheduleBusy={scheduleBusy}
              scheduleError={scheduleError}
              onConfirmSchedule={onConfirmSchedule}
              onDismissSchedule={onDismissSchedule}
              onOpenSchedule={onOpenSchedule}
            />
          ) : (
            <article
              key={m.id}
              className='rounded-12 border border-transparent bg-solid-gray-50 p-4 lg:px-6'
            >
              <h2 className='sr-only'>あなたの質問</h2>
              <p className='whitespace-pre-wrap break-words text-std-16N-170 text-solid-gray-800'>
                {m.content}
              </p>
            </article>
          );
        })}
        {submitting && messages[messages.length - 1]?.role !== 'assistant' && (
          <div>
            <AgentSteps traces={stepTraces(liveSteps)} />
            <ThinkingLine steps={liveSteps} />
          </div>
        )}
      </div>

      <div className='relative z-10 flex shrink-0 flex-col items-center justify-center border-t border-t-solid-gray-800 bg-white pb-2'>
        <form
          className='w-full'
          onSubmit={(e) => {
            e.preventDefault();
            if (submitting || !draft.trim() || !llmEnabled) return;
            onSend();
          }}
          aria-labelledby='notebook-chat-input-heading'
        >
          <h2 id='notebook-chat-input-heading' className='sr-only'>
            {empty
              ? '調べたいことやお困りごとなど、何でも入力してみましょう'
              : '追加で質問や不明点などあれば返答してみましょう'}
          </h2>
          <SupportText id='notebook-chat-submit-hint' className='mb-1'>
            {hint}
          </SupportText>
          <div className='relative flex items-end bg-white'>
            <div className='flex w-full flex-col gap-2'>
              <AutoResizeTextarea
                id='notebook-chat'
                className='resize-none'
                rows={empty ? 2 : 1}
                value={draft}
                placeholder={
                  empty
                    ? '調べたいことやお困りごとなど、何でも入力してみましょう'
                    : '追加で質問や不明点などあれば返答してみましょう'
                }
                aria-labelledby='notebook-chat-input-heading'
                aria-describedby='notebook-chat-submit-hint'
                onKeyDown={requestSubmitOnEnter}
                onChange={(e) => onDraftChange(e.target.value)}
              />
              {readingLabel ? (
                <p
                  role='status'
                  className='flex items-center gap-2 text-dns-14N-130 text-solid-gray-700'
                >
                  <PiSpinnerGap aria-hidden={true} className='size-4 shrink-0 animate-spin' />
                  {readingLabel}
                </p>
              ) : null}
              <div className='flex w-full items-start gap-6'>
                <div className='flex min-w-0 flex-1 flex-wrap items-center gap-2'>
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    aria-busy={attaching || undefined}
                    title={
                      attaching
                        ? 'ファイルを参考資料に取り込んでいます'
                        : `文書は${uploadLimitMb}MBまで`
                    }
                    className='inline-flex shrink-0 items-center justify-center gap-1'
                    onClick={() => {
                      if (attaching) return;
                      onAttach();
                    }}
                  >
                    {attaching ? (
                      <PiSpinnerGap aria-hidden={true} className='size-4 shrink-0 animate-spin' />
                    ) : (
                      <AttachmentIcon aria-hidden={true} className='shrink-0' />
                    )}
                    ファイルを添付
                  </Button>
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    aria-busy={knowledgeBusy || undefined}
                    title={knowledgeBusy ? 'ナレッジを参考資料に取り込んでいます' : undefined}
                    className='inline-flex shrink-0 items-center justify-center gap-1'
                    onClick={onOpenKnowledge}
                  >
                    {knowledgeBusy ? (
                      <PiSpinnerGap aria-hidden={true} className='size-4 shrink-0 animate-spin' />
                    ) : (
                      <SearchIcon aria-hidden={true} className='size-6 shrink-0' />
                    )}
                    ナレッジ選択
                  </Button>
                  <Switch
                    className='flex shrink-0 items-center self-stretch'
                    checked={webSearchOn}
                    disabled={!webSearchAvailable}
                    title={
                      webSearchAvailable
                        ? 'MCP の Web検索と連動します'
                        : 'Web検索の接続先がありません'
                    }
                    onSwitch={onWebSearch}
                    label={webSearchOn ? 'Web検索 On' : 'Web検索 Off'}
                  />
                  {notice && (
                    <p role='status' className='min-w-0 text-dns-14N-130 text-solid-gray-800'>
                      {notice}
                    </p>
                  )}
                </div>
                <LoadingButton
                  type='submit'
                  variant='solid-fill'
                  size='md'
                  disabled={submitting || !llmEnabled}
                  loading={submitting}
                  className='relative z-10 ml-auto inline-flex min-w-36 shrink-0 items-center justify-center gap-1'
                >
                  <SendIcon aria-hidden={true} className='shrink-0' />
                  {submitting ? '生成中...' : '送信'}
                </LoadingButton>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
