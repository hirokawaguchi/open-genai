import { useEffect, useRef, type RefObject } from 'react';
import { PiSpinnerGap } from 'react-icons/pi';
import { latexToPlain } from '@/components/latexToPlain';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { SupportText } from '@/components/ui/dads/SupportText';
import { AttachmentIcon } from '@/components/ui/icons/AttachmentIcon';
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
import { toolLabel } from './toolLabels';
import type { NotebookMessage, NotebookPiiHit, NotebookToolTrace } from './types';

export type NotebookFileNotice = {
  id: string;
  filename: string;
  message?: string;
  categories?: string[];
  hits?: NotebookPiiHit[];
};

type Props = {
  messages: NotebookMessage[];
  draft: string;
  submitting: boolean;
  liveSteps?: string[];
  llmEnabled: boolean;
  attaching: boolean;
  knowledgeBusy: boolean;
  uploadLimitMb: number;
  notice?: string | null;
  fileNotices?: NotebookFileNotice[];
  webSearchOn: boolean;
  webSearchAvailable: boolean;
  onWebSearch: (next: boolean) => void;
  onAttach: () => void;
  onOpenKnowledge: () => void;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  sessionId: string | null;
  onRetry: () => void;
};

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

const FilePiiNotice = ({ notice }: { notice: NotebookFileNotice }) => {
  const hits = notice.hits ?? [];
  const lines = (notice.message || '').split('\n').filter(Boolean);
  return (
    <div className='text-orange-800 whitespace-pre-wrap'>
      <p className='break-all text-solid-gray-800'>{notice.filename}</p>
      <p>
        ＊{lines[0] || `個人情報の可能性: ${(notice.categories ?? []).join('・')}`}
      </p>
      {hits.length > 0 ? (
        <ul className='mt-1 list-disc pl-5'>
          {hits.slice(0, 6).map((hit, index) => (
            <li key={`${hit.category}-${hit.offset ?? index}-${hit.match}`}>
              {hit.category}: 「{hit.context || hit.match}」
            </li>
          ))}
        </ul>
      ) : (
        lines.slice(1).map((line) => <p key={line}>{line}</p>)
      )}
    </div>
  );
};

const AnswerActions = ({
  sessionId,
  message,
  allowRetry,
  onRetry,
  copyRef,
}: {
  sessionId: string | null;
  message: NotebookMessage;
  allowRetry: boolean;
  onRetry: () => void;
  copyRef: RefObject<HTMLDivElement | null>;
}) => {
  const text = message.content.trim();
  if (!text || !sessionId || message.id.startsWith('local-')) return null;
  const plain = latexToPlain(message.content);
  const loadDiagram = () =>
    teamApi
      .post<{ status: 'none' | 'ready'; mermaid?: string }>(
        `notebook/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(message.id)}/diagram`,
        {},
      )
      .then((res) => res.data);
  const loadImage = () =>
    teamApi
      .post<{ status: 'none' | 'ready'; image?: string }>(
        `notebook/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(message.id)}/image`,
        {},
      )
      .then((res) => res.data);
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
    </div>
  );
};

const AssistantTurn = ({
  message,
  sessionId,
  pending,
  liveSteps,
  allowRetry,
  onRetry,
}: {
  message: NotebookMessage;
  sessionId: string | null;
  pending: boolean;
  liveSteps: string[];
  allowRetry: boolean;
  onRetry: () => void;
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
        </div>
      )}
      {pending && <ThinkingLine steps={liveSteps} />}
      {!pending && (
        <AnswerActions
          sessionId={sessionId}
          message={message}
          allowRetry={allowRetry}
          onRetry={onRetry}
          copyRef={copyRef}
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
  fileNotices = [],
  webSearchOn,
  webSearchAvailable,
  onWebSearch,
  onAttach,
  onOpenKnowledge,
  onDraftChange,
  onSend,
  sessionId,
  onRetry,
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
          return m.role === 'assistant' ? (
            <AssistantTurn
              key={m.id}
              message={m}
              sessionId={sessionId}
              pending={pending}
              liveSteps={pending ? liveSteps : []}
              allowRetry={latest && !submitting}
              onRetry={onRetry}
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
              {fileNotices.length > 0 && (
                <div className='flex flex-col gap-2 text-dns-14N-130'>
                  {fileNotices.map((item) => (
                    <FilePiiNotice key={item.id} notice={item} />
                  ))}
                </div>
              )}
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
