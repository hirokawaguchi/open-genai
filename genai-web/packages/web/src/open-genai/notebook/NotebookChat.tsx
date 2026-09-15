import { useEffect, useRef, useState } from 'react';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useSubmitKey } from '@/hooks/useSubmitKey';
import { requestSubmitOnEnter } from '@/utils/keyboard';
import { ChatAnswer } from './Citations';
import { toolLabel } from './toolLabels';
import type { NotebookItem, NotebookMessage, NotebookSkill, NotebookToolTrace } from './types';

type Props = {
  messages: NotebookMessage[];
  items: NotebookItem[];
  skills: NotebookSkill[];
  skillId: string;
  applyItemId: string;
  draft: string;
  submitting: boolean;
  llmEnabled: boolean;
  onSkillIdChange: (id: string) => void;
  onApplyItemIdChange: (id: string) => void;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onApplyMessage: (message: NotebookMessage) => void;
};

const AgentSteps = ({
  traces,
  running,
}: {
  traces?: NotebookToolTrace[];
  running?: boolean;
}) => {
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
          {t.result ? (
            <span className='text-solid-gray-600'>
              {' '}
              — {t.result.slice(0, 80)}
              {t.result.length > 80 ? '…' : ''}
            </span>
          ) : null}
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
  submitting,
  llmEnabled,
  onSkillIdChange,
  onApplyItemIdChange,
  onDraftChange,
  onSend,
  onApplyMessage,
}: Props) => {
  const { hint } = useSubmitKey();
  const chatEndRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLDivElement>(null);
  const [formH, setFormH] = useState(0);
  const selectedSkill = skills.find((s) => s.id === skillId);
  const empty = messages.length === 0 && !submitting;

  const lastKey = messages.at(-1)?.id ?? '';
  const lastText = messages.at(-1)?.content ?? '';

  useEffect(() => {
    const node = formRef.current;
    if (!node) return;
    const sync = () => setFormH(node.offsetHeight);
    const ro = new ResizeObserver(sync);
    ro.observe(node);
    sync();
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = chatEndRef.current;
    if (!el) return;
    const id = window.requestAnimationFrame(() => {
      el.scrollIntoView({ block: 'end', behavior: 'instant' });
    });
    return () => window.cancelAnimationFrame(id);
  }, [lastKey, lastText, messages.length, submitting, formH]);

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div className='flex min-h-[40vh] flex-1 flex-col gap-3 py-3'>
        {empty && (
          <p className='text-std-16N-170 text-solid-gray-536'>
            メッセージを入力して会話を始めましょう。調べた手順は回答の上に出ます。
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
          >
            <div
              className={`max-w-[85%] rounded-8 px-4 py-3 text-dns-14N-130 ${
                m.role === 'user'
                  ? 'bg-blue-50 text-solid-gray-800'
                  : 'border border-solid-gray-420 bg-white'
              }`}
            >
              {m.role === 'assistant' ? (
                <>
                  <h2 className='sr-only'>回答</h2>
                  <AgentSteps traces={m.tool_trace} />
                  <ChatAnswer
                    content={m.content}
                    citations={m.citations ?? []}
                    idPrefix={`nb-cite-${m.id}`}
                  />
                  <div className='mt-3 flex flex-wrap items-center gap-2'>
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
                  </div>
                </>
              ) : (
                <>
                  <h2 className='sr-only'>あなたのメッセージ</h2>
                  <p className='whitespace-pre-wrap break-words text-std-16N-170'>{m.content}</p>
                </>
              )}
            </div>
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
        <div ref={chatEndRef} className='h-px' style={{ scrollMarginBottom: formH }} />
      </div>

      <div
        ref={formRef}
        className='sticky bottom-0 z-1 shrink-0 border-t border-t-solid-gray-800 bg-white pb-2'
      >
        <form
          className='w-full'
          onSubmit={(e) => {
            e.preventDefault();
            if (submitting || !draft.trim() || !llmEnabled) return;
            onSend();
          }}
          aria-labelledby='notebook-chat-input-heading'
        >
          <div className='flex flex-wrap items-center gap-2 py-2'>
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
          <h2 id='notebook-chat-input-heading' className='my-1 text-std-16N-170'>
            {empty
              ? '調べたいことやお困りごとなど、何でも入力してみましょう'
              : '追加で質問や不明点などあれば返答してみましょう'}
          </h2>
          <SupportText id='notebook-chat-submit-hint' className='mb-1'>
            {hint}
          </SupportText>
          <div className='flex flex-col gap-2'>
            <AutoResizeTextarea
              id='notebook-chat'
              className='resize-none'
              rows={empty ? 3 : 1}
              value={draft}
              placeholder=''
              aria-labelledby='notebook-chat-input-heading'
              aria-describedby='notebook-chat-submit-hint'
              onKeyDown={requestSubmitOnEnter}
              onChange={(e) => onDraftChange(e.target.value)}
            />
            <div className='flex justify-end'>
              <LoadingButton
                type='submit'
                variant='solid-fill'
                size='md'
                disabled={submitting || !llmEnabled}
                loading={submitting}
                className='inline-flex min-w-36 items-center justify-center gap-1'
              >
                <SendIcon aria-hidden={true} className='shrink-0' />
                {submitting ? '生成中...' : '送信'}
              </LoadingButton>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
