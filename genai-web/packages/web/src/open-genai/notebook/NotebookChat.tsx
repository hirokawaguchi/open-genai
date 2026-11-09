import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useSubmitKey } from '@/hooks/useSubmitKey';
import { requestSubmitOnEnter } from '@/utils/keyboard';
import {
  answerPreviewLine,
  answerRefNumbers,
  insertAnswerRef,
  MAX_ANSWER_REFS,
  numberedAssistantMessages,
} from './answerRefs';
import { ChatAnswer, SourceList } from './Citations';
import { toolLabel } from './toolLabels';
import type {
  NotebookDraft,
  NotebookItem,
  NotebookMessage,
  NotebookSkill,
  NotebookSourceOption,
  NotebookToolTrace,
} from './types';

type Props = {
  messages: NotebookMessage[];
  items: NotebookItem[];
  skills: NotebookSkill[];
  skillId: string;
  applyItemId: string;
  draft: string;
  sources: NotebookSourceOption[];
  selectedSourceIds: string[];
  submitting: boolean;
  llmEnabled: boolean;
  onSkillIdChange: (id: string) => void;
  onApplyItemIdChange: (id: string) => void;
  onToggleSource: (id: string) => void;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onApplyMessage: (message: NotebookMessage) => void;
  onAdoptDrafts: (drafts: NotebookDraft[]) => void;
  onUseAsInstruction: (message: NotebookMessage) => void;
  onOpenEditorTab: () => void;
};

const AnswerRefText = ({ content }: { content: string }) => {
  const nodes: ReactNode[] = [];
  const re = /\[\[回答\s*(\d+)\]\]/g;
  let last = 0;
  for (const match of content.matchAll(re)) {
    const start = match.index ?? 0;
    if (start > last) nodes.push(content.slice(last, start));
    nodes.push(
      <span
        key={`${start}-${match[1]}`}
        className='mx-0.5 inline-block rounded-full border border-blue-900 bg-white px-2 align-baseline text-dns-14N-130 text-blue-900'
      >
        回答 {Number(match[1])}
      </span>,
    );
    last = start + match[0].length;
  }
  if (last < content.length || nodes.length === 0) nodes.push(content.slice(last));
  return <p className='whitespace-pre-wrap break-words text-std-16N-170'>{nodes}</p>;
};

const AgentSteps = ({ traces, running }: { traces?: NotebookToolTrace[]; running?: boolean }) => {
  if (running) {
    return (
      <div className='mb-2 rounded-8 border border-blue-200 bg-blue-50 px-3 py-2 text-dns-14N-130 text-blue-900'>
        <p className='text-std-16B-150'>調べています</p>
        <p className='mt-1 text-solid-gray-700'>
          参考資料と、このノートで有効にしているMCPを使っています。
        </p>
      </div>
    );
  }
  if (!traces?.length) return null;
  return (
    <ol className='mb-2 list-decimal rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-3 py-2 pl-7 text-dns-14N-130 text-solid-gray-800'>
      {traces.map((t, i) => (
        <li key={`${t.name}-${i}`} className='py-0.5'>
          <span className='text-std-16B-150'>{toolLabel(t.name)}</span>
        </li>
      ))}
    </ol>
  );
};

export const NotebookChat = ({
  messages,
  items,
  skills,
  skillId,
  applyItemId,
  draft,
  sources,
  selectedSourceIds,
  submitting,
  llmEnabled,
  onSkillIdChange,
  onApplyItemIdChange,
  onToggleSource,
  onDraftChange,
  onSend,
  onApplyMessage,
  onAdoptDrafts,
  onUseAsInstruction,
  onOpenEditorTab,
}: Props) => {
  const { hint } = useSubmitKey();
  const listRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const caretRef = useRef({ start: 0, end: 0 });
  const pendingCaret = useRef<number | null>(null);
  const selectedSkill = skills.find((s) => s.id === skillId);
  const empty = messages.length === 0 && !submitting;
  const numbered = useMemo(() => numberedAssistantMessages(messages), [messages]);
  const answersByNumber = useMemo(
    () => new Map(numbered.map((item) => [item.n, item.message])),
    [numbered],
  );
  const numberById = useMemo(
    () => new Map(numbered.map((item) => [item.message.id, item.n])),
    [numbered],
  );
  const latestAssistantId = numbered.at(-1)?.message.id ?? '';
  const [openAnswerIds, setOpenAnswerIds] = useState<Set<string> | null>(null);
  const openAnswers = openAnswerIds ?? new Set(latestAssistantId ? [latestAssistantId] : []);
  const openedLatest = useRef('');
  useEffect(() => {
    if (!latestAssistantId || openedLatest.current === latestAssistantId) return;
    openedLatest.current = latestAssistantId;
    setOpenAnswerIds((prev) => {
      const next = new Set(prev ?? []);
      next.add(latestAssistantId);
      return next;
    });
  }, [latestAssistantId]);
  const draftRefs = useMemo(() => answerRefNumbers(draft), [draft]);

  const rememberCaret = () => {
    const el = textareaRef.current;
    if (!el) return;
    caretRef.current = {
      start: el.selectionStart ?? draft.length,
      end: el.selectionEnd ?? draft.length,
    };
  };

  const insertAnswer = (n: number) => {
    if (submitting || n < 1) return;
    const el = textareaRef.current;
    const focused = el != null && document.activeElement === el;
    const start = focused ? (el.selectionStart ?? caretRef.current.start) : caretRef.current.start;
    const end = focused ? (el.selectionEnd ?? caretRef.current.end) : caretRef.current.end;
    const safeStart = Math.min(start, draft.length);
    const safeEnd = Math.min(Math.max(end, safeStart), draft.length);
    const next = insertAnswerRef(draft, n, safeStart, safeEnd);
    pendingCaret.current = next.caret;
    caretRef.current = { start: next.caret, end: next.caret };
    onDraftChange(next.value);
  };

  useEffect(() => {
    const pos = pendingCaret.current;
    if (pos == null) return;
    pendingCaret.current = null;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(pos, pos);
  }, [draft]);

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
  }, [lastKey, lastText, messages.length, submitting]);

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div
        ref={listRef}
        className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain py-3'
      >
        {empty && (
          <p className='text-std-16N-170 text-solid-gray-536'>
            メッセージを入力して会話を始めましょう。調べた手順は回答の上に出ます。
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            {m.role === 'assistant' ? (
              <Disclosure
                className='w-full max-w-[85%] rounded-8 border border-solid-gray-420 bg-white text-dns-14N-130'
                open={openAnswers.has(m.id)}
                onToggle={(event) => {
                  const nextOpen = event.currentTarget.open;
                  setOpenAnswerIds((prev) => {
                    const next = new Set(prev ?? (latestAssistantId ? [latestAssistantId] : []));
                    if (nextOpen) next.add(m.id);
                    else next.delete(m.id);
                    return next;
                  });
                }}
              >
                <DisclosureSummary className='w-full px-4 py-3'>
                  <span className='shrink-0 text-std-16B-150 text-solid-gray-900'>
                    {numberById.has(m.id) ? `回答 ${numberById.get(m.id)}` : '回答'}
                  </span>
                  <span className='min-w-0 truncate text-dns-14N-130 text-solid-gray-600'>
                    {answerPreviewLine(m.content.replace(/^#{1,6}\s+/, ''))}
                  </span>
                </DisclosureSummary>
                <div className='px-4 pb-3'>
                  <AgentSteps traces={m.tool_trace} />
                  <ChatAnswer
                    content={m.content}
                    citations={m.citations ?? []}
                    idPrefix={`nb-cite-${m.id}`}
                  />
                  {(m.drafts?.length ?? 0) > 0 && (
                    <div className='mt-3 flex flex-col gap-2'>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        下書きです。項目にすると正本になります。
                      </p>
                      {m.drafts?.map((chapter, index) => (
                        <div
                          key={`${m.id}-draft-${index}`}
                          className='rounded-8 border border-solid-gray-300 px-3 py-2'
                        >
                          <p className='text-std-16B-150 text-solid-gray-900'>{chapter.label}</p>
                          <p className='mt-1 line-clamp-3 whitespace-pre-wrap text-dns-14N-130 text-solid-gray-700'>
                            {chapter.value}
                          </p>
                          <SourceList citations={chapter.citations ?? []} />
                          <Button
                            type='button'
                            variant='outline'
                            size='xs'
                            className='mt-2'
                            disabled={submitting}
                            onClick={() => onAdoptDrafts([chapter])}
                          >
                            この章を項目にする
                          </Button>
                        </div>
                      ))}
                      {(m.drafts?.length ?? 0) > 1 && (
                        <Button
                          type='button'
                          variant='outline'
                          size='xs'
                          disabled={submitting}
                          onClick={() => onAdoptDrafts(m.drafts ?? [])}
                        >
                          すべての章を項目にする
                        </Button>
                      )}
                    </div>
                  )}
                  <div className='mt-3 flex flex-wrap items-center gap-2'>
                    {numberById.has(m.id) ? (
                      <Button
                        type='button'
                        variant='outline'
                        size='xs'
                        disabled={submitting}
                        onClick={() => {
                          const n = numberById.get(m.id);
                          if (n) insertAnswer(n);
                        }}
                      >
                        指示に入れる
                      </Button>
                    ) : null}
                    <Button
                      type='button'
                      variant='outline'
                      size='xs'
                      disabled={submitting}
                      onClick={() => onUseAsInstruction(m)}
                    >
                      生成指示にする
                    </Button>
                    {(m.drafts?.length ?? 0) === 0 && (
                      <>
                        <Button
                          type='button'
                          variant='outline'
                          size='xs'
                          onClick={() => onApplyMessage(m)}
                        >
                          {applyItemId ? '項目を更新' : '項目に追加'}
                        </Button>
                        {items.length > 0 && (
                          <Select
                            id={`notebook-apply-${m.id}`}
                            value={applyItemId}
                            onChange={(e) => onApplyItemIdChange(e.target.value)}
                            className='max-w-48'
                          >
                            <option value=''>新規項目</option>
                            {items.map((item) => (
                              <option key={item.id} value={item.id}>
                                {(item.label || '無題').slice(0, 40)}
                              </option>
                            ))}
                          </Select>
                        )}
                      </>
                    )}
                    {m.open_editor && (
                      <Button type='button' variant='outline' size='xs' onClick={onOpenEditorTab}>
                        編集タブを開く
                      </Button>
                    )}
                  </div>
                </div>
              </Disclosure>
            ) : (
              <div className='max-w-[85%] rounded-8 bg-blue-50 px-4 py-3 text-dns-14N-130 text-solid-gray-800'>
                <h2 className='sr-only'>あなたのメッセージ</h2>
                <AnswerRefText content={m.content} />
                {m.source_labels && m.source_labels.length > 0 ? (
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    資料: {m.source_labels.join('、')}
                  </p>
                ) : null}
              </div>
            )}
          </div>
        ))}
        {submitting && (
          <div className='flex justify-start'>
            <div className='max-w-[85%] rounded-8 border border-solid-gray-420 bg-white px-4 py-3'>
              <AgentSteps running />
              <span
                className='inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-solid-gray-300 border-t-blue-900'
                role='status'
                aria-label='生成中'
              />
            </div>
          </div>
        )}
      </div>

      <div className='relative z-10 shrink-0 border-t border-t-solid-gray-800 bg-white pb-2'>
        <form
          className='w-full'
          onSubmit={(e) => {
            e.preventDefault();
            if (submitting || !draft.trim() || !llmEnabled) return;
            onSend();
          }}
          aria-labelledby='notebook-chat-input-heading'
        >
          <div className='flex flex-wrap items-center gap-2 py-1'>
            <label htmlFor='notebook-skill' className='text-dns-14N-130 text-solid-gray-700'>
              AIタイプ
            </label>
            <Select
              id='notebook-skill'
              blockSize='sm'
              value={skillId}
              onChange={(e) => onSkillIdChange(e.target.value)}
              className='max-w-56'
            >
              <option value=''>なし</option>
              {skills.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
            {selectedSkill?.instructions.trim() ? (
              <span className='min-w-0 truncate text-dns-14N-130 text-solid-gray-600'>
                {selectedSkill.instructions.trim()}
              </span>
            ) : null}
          </div>
          <h2 id='notebook-chat-input-heading' className='sr-only'>
            {empty
              ? '調べたいことやお困りごとなど、何でも入力してみましょう'
              : '追加で質問や不明点などあれば返答してみましょう'}
          </h2>
          {sources.length > 0 ? (
            <div className='mb-1 flex flex-wrap items-center gap-2'>
              <p id='notebook-source-scope' className='text-dns-14N-130 text-solid-gray-700'>
                この送信で見る資料
                <span className='text-solid-gray-600'>（未選択ならすべて）</span>
              </p>
              <div
                role='group'
                aria-labelledby='notebook-source-scope'
                className='flex flex-wrap gap-2'
              >
                {sources.map((source) => {
                  const pressed = selectedSourceIds.includes(source.id);
                  return (
                    <button
                      key={source.id}
                      type='button'
                      aria-pressed={pressed}
                      title={source.name}
                      onClick={() => onToggleSource(source.id)}
                      className={`inline-block max-w-48 truncate rounded-full border px-3 py-1 text-left text-dns-14N-130 ${
                        pressed
                          ? 'border-blue-900 bg-blue-50 text-blue-900'
                          : 'border-solid-gray-420 bg-white text-solid-gray-800'
                      }`}
                    >
                      {source.name}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
          <div className='flex flex-col gap-1'>
            <div className='flex items-end gap-2'>
              <AutoResizeTextarea
                id='notebook-chat'
                ref={textareaRef}
                className='min-w-0 flex-1 resize-none px-3! py-2!'
                rows={1}
                maxHeight={112}
                value={draft}
                placeholder=''
                aria-labelledby='notebook-chat-input-heading'
                aria-describedby='notebook-chat-submit-hint'
                onKeyDown={requestSubmitOnEnter}
                onSelect={rememberCaret}
                onKeyUp={rememberCaret}
                onClick={rememberCaret}
                onBlur={rememberCaret}
                onChange={(e) => {
                  rememberCaret();
                  onDraftChange(e.target.value);
                }}
              />
              <LoadingButton
                type='submit'
                variant='solid-fill'
                size='md'
                disabled={submitting || !llmEnabled}
                loading={submitting}
                className='inline-flex min-w-28 shrink-0 items-center justify-center gap-1'
              >
                <SendIcon aria-hidden={true} className='shrink-0' />
                {submitting ? '生成中...' : '送信'}
              </LoadingButton>
            </div>
            <SupportText id='notebook-chat-submit-hint'>
              {hint}
              {numbered.length > 0
                ? ' 過去の回答は「指示に入れる」で、文の途中に番号を差し込めます。'
                : ''}
            </SupportText>
            {draftRefs.length > 0 ? (
              <div>
                <p className='text-dns-14N-130 text-solid-gray-700'>この文で指定した回答</p>
                <ul className='mt-1 flex flex-col gap-1'>
                  {draftRefs.map((n) => {
                    const message = answersByNumber.get(n);
                    return (
                      <li key={n} className='truncate text-dns-14N-130 text-solid-gray-700'>
                        <span className='text-std-16B-150 text-blue-900'>回答 {n}</span>{' '}
                        {message ? (
                          answerPreviewLine(message.content)
                        ) : (
                          <span className='text-error-1'>このノートにありません</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {draftRefs.length > MAX_ANSWER_REFS ? (
                  <p className='mt-1 text-dns-14N-130 text-error-1'>
                    指定できる過去の回答は5件までです
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );
};
