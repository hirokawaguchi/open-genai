import { useEffect, useRef, useState } from 'react';
import { PiChatCircleBold, PiListChecksBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { Textarea } from '@/components/ui/dads/Textarea';
import { Markdown } from '@/components/Markdown';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { NOTEBOOK_EXAPP_ID } from '@/layout/navItems';
import { ApiError } from '@/lib/fetcher';
import { useDocs, useScopes } from '@/open-genai/knowledge/useKnowledge';
import {
  downloadHearingSheetTemplate,
  downloadHearingSheetWorkbook,
  fileToBase64,
  useNotebookActions,
  useNotebookConfig,
  useNotebookSession,
  useNotebookSessions,
} from './useNotebook';
import { ChatAnswer, SourceList } from './Citations';
import { formatNotebookMarkdown, stripCitationMarks, usedCitations } from './formatMarkdown';
import type { NotebookBriefing, NotebookMessage } from './types';

const PANE_TABS = [
  { id: 'items' as const, label: '項目', icon: PiListChecksBold },
  { id: 'chat' as const, label: '対話', icon: PiChatCircleBold },
];

const Spinner = () => (
  <span
    className='inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-solid-gray-300 border-t-blue-900'
    role='status'
    aria-label='処理中'
  />
);

const SourceBriefing = ({ briefing }: { briefing?: NotebookBriefing }) => {
  if (!briefing?.summary && !briefing?.outline?.length && !briefing?.terms?.length) {
    return null;
  }
  return (
    <div className='mt-2 space-y-1 text-dns-14N-130 text-solid-gray-700'>
      {briefing.summary && <p>{briefing.summary}</p>}
      {!!briefing.outline?.length && (
        <p className='text-solid-gray-600'>目次: {briefing.outline.slice(0, 8).join(' / ')}</p>
      )}
      {!!briefing.terms?.length && (
        <p className='text-solid-gray-600'>用語: {briefing.terms.slice(0, 8).join('、')}</p>
      )}
    </div>
  );
};

const UnavailableNotice = ({ message }: { message?: string }) => (
  <div
    className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
    role='status'
  >
    <p className='text-std-16B-150 text-solid-gray-900'>
      ノートブックに接続できません
    </p>
    <p className='mt-2 text-solid-gray-700'>
      {message || '`docker compose up -d` でサービスを起動してください。'}
    </p>
    <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
      docker compose up -d --build
    </pre>
  </div>
);

export const NotebookPage = () => {
  const { documentTitle } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    NOTEBOOK_EXAPP_ID,
    'ノートブック',
  );
  const { config, isLoading: configLoading, unavailable } = useNotebookConfig();
  const { sessions, mutate: mutateSessions } = useNotebookSessions();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { detail, mutate: mutateDetail } = useNotebookSession(sessionId);
  const actions = useNotebookActions();
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState('');
  const [instruction, setInstruction] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { label: string; value: string }>>({});
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [pane, setPane] = useState<'items' | 'chat'>('items');
  const [chatDraft, setChatDraft] = useState('');
  const [knowledgeScope, setKnowledgeScope] = useState('');
  const [knowledgeDocId, setKnowledgeDocId] = useState('');
  const [editingValueId, setEditingValueId] = useState<string | null>(null);
  const { scopes } = useScopes();
  const { docs: knowledgeDocs } = useDocs(knowledgeScope || undefined);

  useEffect(() => {
    if (!detail) return;
    setTitle(detail.title);
    setInstruction(detail.instruction);
    setDrafts(
      Object.fromEntries(detail.items.map((i) => [i.id, { label: i.label, value: i.value }])),
    );
  }, [detail]);

  useEffect(() => {
    if (!knowledgeScope && scopes.length > 0) {
      setKnowledgeScope(scopes[0].scope);
    }
  }, [knowledgeScope, scopes]);

  const accept = (config?.accept ?? ['.pdf', '.docx', '.xlsx', '.pptx', '.txt', '.md', '.csv', '.html', '.json']).join(
    ',',
  );
  const llmEnabled = config?.llm?.enabled !== false;

  const refresh = async (next?: typeof detail) => {
    if (next) {
      await mutateDetail(next, { revalidate: false });
    } else {
      await mutateDetail();
    }
    await mutateSessions();
  };

  const onCreate = async () => {
    const created = await actions.createSession();
    if (!created) return;
    setSessionId(created.id);
    await refresh(created);
  };

  const onSelect = (id: string) => {
    setSessionId(id);
    actions.setError(null);
    setDownloadError(null);
  };

  const onSaveTitle = async () => {
    if (!sessionId || !detail || title === detail.title) return;
    const next = await actions.updateSession(sessionId, { title });
    if (next) await refresh(next);
  };

  const onSaveInstruction = async () => {
    if (!sessionId || !detail || instruction === detail.instruction) return;
    const next = await actions.updateSession(sessionId, { instruction });
    if (next) await refresh(next);
  };

  const onSaveItem = async (itemId: string, field: 'label' | 'value') => {
    if (!sessionId || !detail) return;
    const draft = drafts[itemId];
    const current = detail.items.find((i) => i.id === itemId);
    if (!draft || !current || draft[field] === current[field]) return;
    const next = await actions.updateItem(sessionId, itemId, { [field]: draft[field] });
    if (next) await refresh(next);
  };

  const onAddItem = async () => {
    if (!sessionId) return;
    const next = await actions.addItem(sessionId);
    if (next) await refresh(next);
  };

  const onDeleteItem = async (itemId: string) => {
    if (!sessionId) return;
    const next = await actions.deleteItem(sessionId, itemId);
    if (next) await refresh(next);
  };

  const onGenerate = async (itemId: string) => {
    if (!sessionId) return;
    await onSaveItem(itemId, 'label');
    const next = await actions.generateItem(sessionId, itemId);
    if (next) await refresh(next);
  };

  const onPickFiles = async (files: FileList | null) => {
    if (!sessionId || !files?.length) return;
    let latest = detail;
    for (const file of Array.from(files)) {
      const content = await fileToBase64(file);
      latest = (await actions.addFile(sessionId, file.name, content)) ?? latest;
    }
    if (fileRef.current) fileRef.current.value = '';
    if (latest) await refresh(latest);
  };

  const onDeleteFile = async (fileId: string) => {
    if (!sessionId) return;
    const next = await actions.deleteFile(sessionId, fileId);
    if (next) await refresh(next);
  };

  const onAddKnowledge = async () => {
    if (!sessionId || !knowledgeScope || !knowledgeDocId) return;
    const next = await actions.addKnowledgeRef(sessionId, {
      scope: knowledgeScope,
      doc_id: knowledgeDocId,
    });
    if (next) {
      setKnowledgeDocId('');
      await refresh(next);
    }
  };

  const onDeleteKnowledge = async (refId: string) => {
    if (!sessionId) return;
    const next = await actions.deleteKnowledgeRef(sessionId, refId);
    if (next) await refresh(next);
  };

  const onChat = async () => {
    if (!sessionId || !chatDraft.trim()) return;
    const q = chatDraft.trim();
    setChatDraft('');
    const next = await actions.chat(sessionId, q);
    if (next) await refresh(next);
  };

  const questionForAssistant = (messageId: string): string => {
    const messages = detail?.messages ?? [];
    const idx = messages.findIndex((m) => m.id === messageId);
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user' && messages[i].content.trim()) {
        return messages[i].content.trim();
      }
    }
    return '';
  };

  const onChatToItem = async (message: NotebookMessage) => {
    if (!sessionId || message.role !== 'assistant') return;
    const added = await actions.addItem(sessionId);
    const item = added?.items[added.items.length - 1];
    if (!item) return;
    const next = await actions.updateItem(sessionId, item.id, {
      label: questionForAssistant(message.id) || '対話から追加',
      value: stripCitationMarks(message.content),
      citations: usedCitations(message.content, message.citations ?? []),
    });
    if (next) {
      setPane('items');
      await refresh(next);
    }
  };

  const onDeleteSession = async () => {
    if (!sessionId) return;
    if (!window.confirm('このノートを削除しますか？')) return;
    const ok = await actions.deleteSession(sessionId);
    if (!ok) return;
    setSessionId(null);
    await mutateSessions();
  };

  const onDownloadTemplate = async () => {
    setDownloadError(null);
    try {
      await downloadHearingSheetTemplate();
    } catch (e) {
      setDownloadError(
        e instanceof ApiError
          ? ((e.data as { error?: string } | undefined)?.error ?? '雛形の取得に失敗しました。')
          : '雛形の取得に失敗しました。',
      );
    }
  };

  const onDownloadFilled = async () => {
    if (!sessionId) return;
    setDownloadError(null);
    try {
      await onSaveInstruction();
      await downloadHearingSheetWorkbook(sessionId);
    } catch (e) {
      setDownloadError(
        e instanceof ApiError
          ? ((e.data as { error?: string } | undefined)?.error ?? 'ダウンロードに失敗しました。')
          : 'ダウンロードに失敗しました。',
      );
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-4 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={NOTEBOOK_EXAPP_ID}
          fallbackTitle='ノートブック'
          fallbackDescription='参考資料を集めて調べ、項目として整理します。必要ならヒアリングシート（Excel）も作れます。'
          fallbackHowTo={
            <>
              <p>・左でノートを選び、参考ファイルや既存ナレッジをソースに追加します。</p>
              <p>・取込時に全文を構造化します。右の項目（設問）が作業の主領域です。</p>
              <p>・各行の「生成」と対話は、同じソースだけを根拠にします。</p>
              <p>・記入済みヒアリングシートをダウンロードし、Markdown エディタの生成入力として使えます。</p>
              {config?.llm?.model && <p>・利用モデル: {config.llm.model}</p>}
            </>
          }
        />

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <UnavailableNotice message={config?.error} />
        )}

        {!unavailable && (
          <div className='grid gap-6 lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]'>
            <aside className='flex flex-col gap-4'>
              <div className='flex flex-wrap gap-2'>
                <Button type='button' variant='solid-fill' size='md' onClick={() => void onCreate()}>
                  新しいノート
                </Button>
                <Button type='button' variant='outline' size='md' onClick={() => void onDownloadTemplate()}>
                  空の雛形
                </Button>
              </div>

              <section>
                <h2 className='mb-2 text-std-16B-150'>ノート一覧</h2>
                {sessions.length === 0 ? (
                  <p className='text-dns-14N-130 text-solid-gray-600'>まだノートがありません。</p>
                ) : (
                  <ul className='flex flex-col gap-1'>
                    {sessions.map((s) => (
                      <li key={s.id}>
                        <button
                          type='button'
                          onClick={() => onSelect(s.id)}
                          className={
                            s.id === sessionId
                              ? 'w-full rounded-8 bg-blue-50 px-3 py-2 text-left text-std-16B-150 text-blue-900'
                              : 'w-full rounded-8 px-3 py-2 text-left text-std-16N-170 text-solid-gray-800 hover:bg-solid-gray-50'
                          }
                        >
                          <span className='block'>{s.title || '無題'}</span>
                          <span className='block text-dns-14N-130 text-solid-gray-600'>
                            項目 {s.filled_count ?? 0}/{s.item_count ?? 0}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {detail && (
                <section className='flex flex-col gap-2'>
                  <h2 className='text-std-16B-150'>ソース</h2>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    PDF / Word / Excel / PowerPoint / テキストなど（上限{' '}
                    {Math.round((config?.max_upload_bytes ?? 20 * 1024 * 1024) / 1024 / 1024)}MB）
                  </p>
                  <input
                    ref={fileRef}
                    type='file'
                    multiple
                    accept={accept}
                    className='sr-only'
                    onChange={(e) => void onPickFiles(e.target.files)}
                  />
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={actions.submitting || undefined}
                    onClick={() => fileRef.current?.click()}
                  >
                    ファイルを追加
                  </Button>
                  {detail.files.length === 0 ? (
                    <p className='text-dns-14N-130 text-solid-gray-600'>未追加です。</p>
                  ) : (
                    <ul className='flex flex-col gap-2'>
                      {detail.files.map((f) => (
                        <li
                          key={f.id}
                          className='rounded-8 border border-solid-gray-300 px-3 py-2 text-dns-14N-130'
                        >
                          <div className='flex items-start justify-between gap-2'>
                            <span className='break-all text-solid-gray-900'>
                              {f.filename}
                              {!!f.node_count && (
                                <span className='ml-1 text-solid-gray-600'>（{f.node_count}節）</span>
                              )}
                            </span>
                            <Button
                              type='button'
                              variant='outline'
                              size='xs'
                              onClick={() => void onDeleteFile(f.id)}
                            >
                              削除
                            </Button>
                          </div>
                          {f.error && <p className='mt-1 text-error-1'>{f.error}</p>}
                          {!f.error && <SourceBriefing briefing={f.briefing} />}
                        </li>
                      ))}
                    </ul>
                  )}

                  <h3 className='mt-3 text-std-16B-150'>ナレッジから追加</h3>
                  <Select
                    id='notebook-knowledge-scope'
                    blockSize='sm'
                    value={knowledgeScope}
                    onChange={(e) => {
                      setKnowledgeScope(e.target.value);
                      setKnowledgeDocId('');
                    }}
                  >
                    {scopes.map((s) => (
                      <option key={s.scope} value={s.scope}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                  <Select
                    id='notebook-knowledge-doc'
                    blockSize='sm'
                    value={knowledgeDocId}
                    onChange={(e) => setKnowledgeDocId(e.target.value)}
                  >
                    <option value=''>資料を選ぶ</option>
                    {knowledgeDocs
                      .filter((d) => d.ingest_status !== 'failed')
                      .map((d) => (
                        <option key={d.doc_id} value={d.doc_id}>
                          {d.source}
                        </option>
                      ))}
                  </Select>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={actions.submitting || !knowledgeDocId || undefined}
                    onClick={() => void onAddKnowledge()}
                  >
                    ソースに追加
                  </Button>
                  {(detail.knowledge_refs ?? []).map((ref) => (
                    <div
                      key={ref.id}
                      className='rounded-8 border border-solid-gray-300 px-3 py-2 text-dns-14N-130'
                    >
                      <div className='flex items-start justify-between gap-2'>
                        <span className='break-all text-solid-gray-900'>
                          {ref.title || ref.source}
                          {!!ref.node_count && (
                            <span className='ml-1 text-solid-gray-600'>（{ref.node_count}節）</span>
                          )}
                        </span>
                        <Button
                          type='button'
                          variant='outline'
                          size='xs'
                          onClick={() => void onDeleteKnowledge(ref.id)}
                        >
                          削除
                        </Button>
                      </div>
                      <SourceBriefing briefing={ref.briefing} />
                    </div>
                  ))}
                </section>
              )}
            </aside>

            <section className='flex min-w-0 flex-col gap-4'>
              {!detail ? (
                <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4 text-std-16N-170 text-solid-gray-700'>
                  左でノートを選ぶか、「新しいノート」を作成してください。
                </div>
              ) : (
                <>
                  <div
                    className='flex flex-wrap gap-2 border-b border-solid-gray-300'
                    role='tablist'
                    aria-label='ノートの表示'
                  >
                    {PANE_TABS.map((t) => {
                      const Icon = t.icon;
                      return (
                        <button
                          key={t.id}
                          type='button'
                          role='tab'
                          aria-selected={pane === t.id}
                          onClick={() => setPane(t.id)}
                          className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-oln-16B-100 ${
                            pane === t.id
                              ? 'border-blue-900 text-blue-900'
                              : 'border-transparent text-solid-gray-600 hover:text-solid-gray-900'
                          }`}
                        >
                          <Icon aria-hidden={true} className='size-5' />
                          {t.label}
                        </button>
                      );
                    })}
                  </div>

                  <div className='flex flex-col gap-2'>
                    <Label htmlFor='notebook-title'>ノート名</Label>
                    <Input
                      id='notebook-title'
                      blockSize='md'
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      onBlur={() => void onSaveTitle()}
                    />
                  </div>

                  {pane === 'items' && <div className='flex flex-col gap-3'>
                    <div className='flex items-center justify-between gap-2'>
                      <h2 className='text-std-18B-160'>項目</h2>
                      <Button type='button' variant='outline' size='sm' onClick={() => void onAddItem()}>
                        項目を追加
                      </Button>
                    </div>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      項目名が設問です。生成はソースの該当節だけを根拠にします。
                    </p>
                    {detail.items.length === 0 && (
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        「項目を追加」から設問を増やしてください。
                      </p>
                    )}
                    {detail.items.map((item, index) => {
                      const draft = drafts[item.id] ?? { label: item.label, value: item.value };
                      const busy = actions.generatingId === item.id;
                      return (
                        <article
                          key={item.id}
                          className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 p-3'
                        >
                          <div className='flex flex-wrap items-center justify-between gap-2'>
                            <Label htmlFor={`notebook-label-${item.id}`}>項目 {index + 1}</Label>
                            <div className='flex flex-wrap gap-2'>
                              <Button
                                type='button'
                                variant='solid-fill'
                                size='sm'
                                aria-disabled={busy || !llmEnabled || !draft.label.trim() || undefined}
                                onClick={() => {
                                  if (busy || !llmEnabled || !draft.label.trim()) return;
                                  void onGenerate(item.id);
                                }}
                              >
                                {busy ? (
                                  <>
                                    <Spinner /> 生成中
                                  </>
                                ) : llmEnabled ? (
                                  '生成'
                                ) : (
                                  'LLM 未設定'
                                )}
                              </Button>
                              <Button
                                type='button'
                                variant='outline'
                                size='sm'
                                onClick={() => void onDeleteItem(item.id)}
                              >
                                削除
                              </Button>
                            </div>
                          </div>
                          <Input
                            id={`notebook-label-${item.id}`}
                            blockSize='md'
                            placeholder='例: 対象業務は何か'
                            value={draft.label}
                            onChange={(e) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [item.id]: { ...draft, label: e.target.value },
                              }))
                            }
                            onBlur={() => void onSaveItem(item.id, 'label')}
                          />
                          {editingValueId === item.id || !draft.value.trim() ? (
                            <Textarea
                              id={`notebook-value-${item.id}`}
                              rows={5}
                              placeholder='値（手入力または生成）'
                              value={draft.value}
                              onChange={(e) =>
                                setDrafts((prev) => ({
                                  ...prev,
                                  [item.id]: { ...draft, value: e.target.value },
                                }))
                              }
                              onBlur={() => {
                                void onSaveItem(item.id, 'value');
                                if (draft.value.trim()) setEditingValueId(null);
                              }}
                            />
                          ) : (
                            <div className='rounded-8 border border-solid-gray-300 px-3 py-2'>
                              <div className='mb-2 flex justify-end'>
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='xs'
                                  onClick={() => setEditingValueId(item.id)}
                                >
                                  編集
                                </Button>
                              </div>
                              <Markdown>{formatNotebookMarkdown(draft.value)}</Markdown>
                            </div>
                          )}
                          <SourceList citations={item.citations ?? []} />
                        </article>
                      );
                    })}
                  </div>}

                  {pane === 'chat' && (
                    <div className='flex flex-col gap-3'>
                      <h2 className='text-std-18B-160'>対話</h2>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        同じソースだけを根拠にします。分かったことは項目へ移せます。
                      </p>
                      <ul className='flex flex-col gap-3'>
                        {(detail.messages ?? []).map((m) => (
                          <li
                            key={m.id}
                            className='rounded-8 border border-solid-gray-300 px-3 py-2 text-dns-14N-130'
                          >
                            <p className='text-std-16B-150'>
                              {m.role === 'user' ? '質問' : '回答'}
                            </p>
                            {m.role === 'assistant' ? (
                              <ChatAnswer
                                content={m.content}
                                citations={m.citations ?? []}
                                idPrefix={`nb-cite-${m.id}`}
                              />
                            ) : (
                              <p className='mt-1 whitespace-pre-wrap text-solid-gray-900'>{m.content}</p>
                            )}
                            {m.role === 'assistant' && (
                              <div className='mt-2'>
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='xs'
                                  onClick={() => void onChatToItem(m)}
                                >
                                  項目に追加
                                </Button>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                      <Textarea
                        id='notebook-chat'
                        rows={3}
                        value={chatDraft}
                        placeholder='ソースについて質問'
                        onChange={(e) => setChatDraft(e.target.value)}
                      />
                      <Button
                        type='button'
                        variant='solid-fill'
                        size='md'
                        aria-disabled={actions.submitting || !chatDraft.trim() || !llmEnabled || undefined}
                        onClick={() => {
                          if (actions.submitting || !chatDraft.trim() || !llmEnabled) return;
                          void onChat();
                        }}
                      >
                        {actions.submitting ? (
                          <>
                            <Spinner /> 送信中
                          </>
                        ) : (
                          '送信'
                        )}
                      </Button>
                    </div>
                  )}

                  {pane === 'items' && (
                    <div className='flex flex-col gap-2'>
                      <Label htmlFor='notebook-instruction'>生成指示</Label>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        Markdown エディタ／generate-app へ渡す処理の指示です。
                      </p>
                      <Textarea
                        id='notebook-instruction'
                        rows={4}
                        value={instruction}
                        onChange={(e) => setInstruction(e.target.value)}
                        onBlur={() => void onSaveInstruction()}
                      />
                    </div>
                  )}

                  <div className='flex flex-wrap gap-2'>
                    <Button type='button' variant='solid-fill' size='md' onClick={() => void onDownloadFilled()}>
                      記入済みシートをダウンロード
                    </Button>
                    <Button type='button' variant='outline' size='md' onClick={() => void onDeleteSession()}>
                      このノートを削除
                    </Button>
                  </div>
                </>
              )}

              {(actions.error || downloadError) && (
                <p className='text-std-16N-170 text-error-1' role='alert'>
                  {actions.error || downloadError}
                </p>
              )}
            </section>
          </div>
        )}
      </div>
    </LayoutBody>
  );
};
