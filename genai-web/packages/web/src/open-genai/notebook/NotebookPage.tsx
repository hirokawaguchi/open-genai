import { useEffect, useRef, useState } from 'react';
import { PiBookOpenBold, PiFilePlus, PiPuzzlePieceBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { Textarea } from '@/components/ui/dads/Textarea';
import { Switch } from '@/components/ui/Switch';
import { Markdown } from '@/components/Markdown';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
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
  useNotebookMcps,
  useNotebookSession,
  useNotebookSessions,
  useNotebookSkills,
} from './useNotebook';
import { SourceList } from './Citations';
import { NotebookChat } from './NotebookChat';
import { NotebookManageDialog } from './NotebookManageDialog';
import { formatNotebookMarkdown, stripCitationMarks, usedCitations } from './formatMarkdown';
import type { NotebookBriefing, NotebookMessage } from './types';

const PANE_TABS = [
  { id: 'list' as const, label: 'ノート一覧' },
  { id: 'sources' as const, label: '参考資料' },
  { id: 'chat' as const, label: '対話' },
  { id: 'items' as const, label: '項目' },
];

const defaultNoteTitle = (existing: { title: string }[]) => {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const base = `ノート ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const titles = new Set(existing.map((s) => s.title));
  if (!titles.has(base)) return base;
  let n = 2;
  while (titles.has(`${base} (${n})`)) n += 1;
  return `${base} (${n})`;
};

const formatWhen = (iso?: string) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const Spinner = () => (
  <span
    className='inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-solid-gray-300 border-t-blue-900'
    role='status'
    aria-label='処理中'
  />
);

const SourceBriefing = ({ briefing }: { briefing?: NotebookBriefing }) => {
  if (
    !briefing?.summary &&
    !briefing?.outline?.length &&
    !briefing?.terms?.length &&
    !briefing?.ocr
  ) {
    return null;
  }
  return (
    <div className='space-y-1 text-dns-14N-130 text-solid-gray-700'>
      {briefing.ocr && <p className='text-solid-gray-600'>スキャンを OCR で読み取りました。</p>}
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

const SourceCard = ({
  kind,
  name,
  nodeCount,
  error,
  briefing,
  onDelete,
}: {
  kind: 'ファイル' | 'ナレッジ';
  name: string;
  nodeCount?: number;
  error?: string | null;
  briefing?: NotebookBriefing;
  onDelete: () => void;
}) => {
  const hasBody =
    !!error ||
    !!nodeCount ||
    !!briefing?.summary ||
    !!briefing?.outline?.length ||
    !!briefing?.terms?.length ||
    !!briefing?.ocr;
  return (
    <div className='rounded-8 border border-solid-gray-300 px-3 py-2 text-dns-14N-130'>
      <div className='flex items-start justify-between gap-2'>
        <div className='min-w-0'>
          <p className='text-dns-14N-130 text-solid-gray-600'>{kind}</p>
          <p className='break-all text-solid-gray-900'>{name}</p>
        </div>
        <Button type='button' variant='outline' size='xs' onClick={onDelete}>
          削除
        </Button>
      </div>
      {hasBody && (
        <Disclosure className='mt-2'>
          <DisclosureSummary>詳細</DisclosureSummary>
          <div className='mt-2 space-y-1'>
            {error && <p className='text-error-1'>{error}</p>}
            {!!nodeCount && !error && (
              <p className='text-solid-gray-600'>{nodeCount}節</p>
            )}
            {!error && <SourceBriefing briefing={briefing} />}
          </div>
        </Disclosure>
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
  const { skills, mutate: mutateSkills } = useNotebookSkills();
  const { mcps, mutate: mutateMcps } = useNotebookMcps();
  const actions = useNotebookActions();
  const fileRef = useRef<HTMLInputElement>(null);
  const [listTitles, setListTitles] = useState<Record<string, string>>({});
  const [newNoteName, setNewNoteName] = useState('');
  const [instruction, setInstruction] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { label: string; value: string }>>({});
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [pane, setPane] = useState<(typeof PANE_TABS)[number]['id']>('list');
  const [helpOpen, setHelpOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [sessionMcpOpen, setSessionMcpOpen] = useState(false);
  const [chatDraft, setChatDraft] = useState('');
  const [skillId, setSkillId] = useState('');
  const [applyItemId, setApplyItemId] = useState('');
  const [knowledgeScope, setKnowledgeScope] = useState('');
  const [knowledgeDocId, setKnowledgeDocId] = useState('');
  const [editingValueId, setEditingValueId] = useState<string | null>(null);
  const [addingFiles, setAddingFiles] = useState(false);
  const [addingFileLabel, setAddingFileLabel] = useState('');
  const { scopes } = useScopes();
  const { docs: knowledgeDocs } = useDocs(knowledgeScope || undefined);

  useEffect(() => {
    if (!detail) return;
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
    const name = newNoteName.trim();
    if (!name) return;
    const created = await actions.createSession(name);
    if (!created) return;
    setNewNoteName('');
    setPane('chat');
    setSessionId(created.id);
    await refresh(created);
  };

  const onSelect = (id: string) => {
    setPane('chat');
    setSessionId(id);
    actions.setError(null);
    setDownloadError(null);
  };

  const onSaveListTitle = async (id: string) => {
    const nextTitle = (listTitles[id] ?? '').trim() || '無題';
    const current = sessions.find((s) => s.id === id);
    if (!current || nextTitle === current.title) return;
    const next = await actions.updateSession(id, { title: nextTitle });
    if (!next) return;
    if (sessionId === id) await refresh(next);
    else await mutateSessions();
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
    if (!sessionId || !files?.length || addingFiles) return;
    const list = Array.from(files);
    setAddingFiles(true);
    try {
      let latest = detail;
      for (let i = 0; i < list.length; i += 1) {
        const file = list[i];
        setAddingFileLabel(
          list.length > 1 ? `${file.name}（${i + 1}/${list.length}）` : file.name,
        );
        const content = await fileToBase64(file);
        latest = (await actions.addFile(sessionId, file.name, content)) ?? latest;
      }
      if (fileRef.current) fileRef.current.value = '';
      if (latest) await refresh(latest);
    } finally {
      setAddingFiles(false);
      setAddingFileLabel('');
    }
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
    const prev = detail;
    setChatDraft('');
    if (detail) {
      await mutateDetail(
        {
          ...detail,
          messages: [
            ...(detail.messages ?? []),
            {
              id: `local-${crypto.randomUUID()}`,
              role: 'user',
              content: q,
              created_at: new Date().toISOString(),
            },
          ],
        },
        { revalidate: false },
      );
    }
    const next = await actions.chat(sessionId, q, skillId || undefined);
    if (next) {
      await refresh(next);
      return;
    }
    setChatDraft(q);
    if (prev) await mutateDetail(prev, { revalidate: false });
    else await mutateDetail();
  };

  const onCreateSkill = async (name: string, instructions: string) => {
    const created = await actions.createSkill({
      name,
      instructions: instructions || undefined,
    });
    if (!created) return false;
    setSkillId(created.id);
    await mutateSkills();
    return true;
  };

  const onDeleteSkill = async (id: string) => {
    if (!window.confirm('このAIタイプを削除しますか？')) return;
    const ok = await actions.deleteSkill(id);
    if (ok) {
      if (skillId === id) setSkillId('');
      await mutateSkills();
    }
  };

  const onUpdateMcp = async (
    id: string,
    body: { connected?: boolean; prompt?: string; reset_prompt?: boolean },
  ) => {
    const next = await actions.updateMcp(id, body);
    if (!next) return false;
    await mutateMcps();
    if (sessionId) await mutateDetail();
    return true;
  };

  const onCreateMcp = async (name: string, url: string, prompt: string) => {
    const created = await actions.createMcp({ name, url, prompt: prompt || undefined });
    if (!created) return false;
    await mutateMcps();
    if (sessionId) await mutateDetail();
    return true;
  };

  const onDeleteMcp = async (id: string) => {
    if (!window.confirm('この MCP を削除しますか？')) return;
    const ok = await actions.deleteMcp(id);
    if (ok) {
      await mutateMcps();
      if (sessionId) await mutateDetail();
    }
  };

  const onToggleSessionMcp = async (id: string, enabled: boolean) => {
    if (!sessionId) return;
    const next = await actions.updateSession(sessionId, { mcps: [{ id, enabled }] });
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
    const value = stripCitationMarks(message.content);
    const citations = usedCitations(message.content, message.citations ?? []);
    if (applyItemId) {
      const next = await actions.updateItem(sessionId, applyItemId, { value, citations });
      if (next) await refresh(next);
      return;
    }
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

  const onDeleteSession = async (id?: string) => {
    const target = id || sessionId;
    if (!target) return;
    if (!window.confirm('このノートを削除しますか？')) return;
    const ok = await actions.deleteSession(target);
    if (!ok) return;
    if (sessionId === target) {
      setSessionId(null);
      setPane('list');
    }
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

  const sourceCount =
    (detail?.files.length ?? 0) + (detail?.knowledge_refs?.length ?? 0);
  const connectedMcps = (detail?.mcps ?? []).filter((m) => m.connected);
  const enabledMcpCount = connectedMcps.filter((m) => m.enabled).length;

  const needNote = pane !== 'list' && !detail;

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={NOTEBOOK_EXAPP_ID}
          fallbackTitle='ノートブック'
          fallbackDescription='参考資料を集めて調べ、項目として整理します。Markdown エディタに読み込ませるヒアリングシートも作成できます。'
          hideHowTo={true}
        />

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <UnavailableNotice message={config?.error} />
        )}

        {!unavailable && (
          <>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <div className='flex flex-wrap gap-1 overflow-x-auto border-b border-solid-gray-300'>
                {PANE_TABS.map((t) => (
                  <button
                    key={t.id}
                    type='button'
                    onClick={() => setPane(t.id)}
                    className={
                      pane === t.id
                        ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                        : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900'
                    }
                  >
                    {t.id === 'sources' && detail ? `${t.label}（${sourceCount}）` : t.label}
                  </button>
                ))}
              </div>
              <div className='flex flex-wrap gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  className='inline-flex items-center gap-1'
                  onClick={() => setManageOpen(true)}
                >
                  <PiPuzzlePieceBold aria-hidden={true} className='size-4' />
                  AIタイプとMCP
                </Button>
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

            {pane === 'list' && (
              <section className='flex flex-col gap-3'>
                <div className='flex flex-wrap items-end justify-between gap-2'>
                  <h2 className='text-std-18B-160 text-solid-gray-900'>ノート一覧</h2>
                  <div className='flex flex-wrap items-end gap-2'>
                    <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                      新規ノート名
                      <Input
                        id='notebook-new-name'
                        blockSize='sm'
                        value={newNoteName}
                        onChange={(e) => setNewNoteName(e.target.value)}
                        placeholder={defaultNoteTitle(sessions)}
                        className='w-64'
                      />
                    </label>
                    <Button
                      type='button'
                      variant='solid-fill'
                      size='sm'
                      aria-disabled={actions.submitting || !newNoteName.trim() || undefined}
                      onClick={() => {
                        if (actions.submitting || !newNoteName.trim()) return;
                        void onCreate();
                      }}
                    >
                      <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                        <PiFilePlus className='size-4' aria-hidden={true} />
                        作成
                      </span>
                    </Button>
                    <Button type='button' variant='outline' size='sm' onClick={() => void onDownloadTemplate()}>
                      空の雛形
                    </Button>
                  </div>
                </div>
                <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
                  <table className='w-full min-w-[56rem] border-collapse text-dns-14N-130'>
                    <thead>
                      <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                        <th className='w-3/5 min-w-[32rem] px-3 py-2'>ノート名</th>
                        <th className='px-3 py-2'>更新</th>
                        <th className='px-3 py-2'>項目</th>
                        <th className='px-3 py-2 text-right'>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.length === 0 ? (
                        <tr>
                          <td colSpan={4} className='px-3 py-6 text-center text-solid-gray-500'>
                            ノートがありません。右上から新規作成してください。
                          </td>
                        </tr>
                      ) : (
                        sessions.map((s) => (
                          <tr key={s.id} className='border-b border-solid-gray-200'>
                            <td className='w-3/5 min-w-[32rem] px-3 py-2'>
                              <Input
                                id={`notebook-list-title-${s.id}`}
                                blockSize='sm'
                                className='w-full min-w-0'
                                aria-label='ノート名'
                                value={listTitles[s.id] ?? s.title}
                                onChange={(e) =>
                                  setListTitles((prev) => ({ ...prev, [s.id]: e.target.value }))
                                }
                                onBlur={() => void onSaveListTitle(s.id)}
                              />
                            </td>
                            <td className='px-3 py-2 text-solid-gray-600'>{formatWhen(s.updated_at)}</td>
                            <td className='px-3 py-2 text-solid-gray-600'>
                              {s.filled_count ?? 0}/{s.item_count ?? 0}
                            </td>
                            <td className='px-3 py-2 text-right'>
                              <div className='inline-flex gap-2'>
                                <Button type='button' variant='solid-fill' size='xs' onClick={() => onSelect(s.id)}>
                                  開く
                                </Button>
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='xs'
                                  onClick={() => void onDeleteSession(s.id)}
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
              </section>
            )}

            {needNote && (
              <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
                「ノート一覧」タブからノートを開いてください。
              </div>
            )}

            {pane === 'sources' && detail && (
              <section className='flex flex-col gap-3'>
                <h2 className='text-std-18B-160 text-solid-gray-900'>参考資料（{sourceCount}件）</h2>
                <div className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-3'>
                  <p className='text-std-16B-150 text-solid-gray-900'>参考資料を追加</p>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    ノートに取り込む資料です。項目の根拠になります。スキャン PDF は OCR で読みます。PDF / Word / Excel / PowerPoint /
                    テキストなど（上限{' '}
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
                  <div className='grid gap-3 lg:grid-cols-2'>
                    <div className='flex flex-col gap-2'>
                      <p className='text-dns-14N-130 text-solid-gray-700'>ファイル</p>
                      <LoadingButton
                        type='button'
                        variant='solid-fill'
                        size='sm'
                        className='w-fit'
                        disabled={addingFiles || actions.submitting}
                        loading={addingFiles}
                        onClick={() => fileRef.current?.click()}
                      >
                        {addingFiles ? '追加中...' : 'ファイルを追加'}
                      </LoadingButton>
                      {addingFiles && (
                        <p className='flex items-center gap-2 text-dns-14N-130 text-solid-gray-700'>
                          <Spinner />
                          {addingFileLabel
                            ? `${addingFileLabel} を取り込んでいます`
                            : 'ファイルを取り込んでいます'}
                        </p>
                      )}
                    </div>
                    <div className='flex flex-col gap-2'>
                      <p className='text-dns-14N-130 text-solid-gray-700'>ナレッジを取り込む</p>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        選んだ文書のコピーをこのノートに入れます。「このノートのMCP」とは別です。
                      </p>
                      <div className='flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end'>
                        <Select
                          id='notebook-knowledge-scope'
                          blockSize='sm'
                          value={knowledgeScope}
                          onChange={(e) => {
                            setKnowledgeScope(e.target.value);
                            setKnowledgeDocId('');
                          }}
                          className='sm:min-w-40 sm:flex-1'
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
                          className='sm:min-w-40 sm:flex-1'
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
                          variant='solid-fill'
                          size='sm'
                          className='w-fit'
                          aria-disabled={actions.submitting || !knowledgeDocId || undefined}
                          onClick={() => void onAddKnowledge()}
                        >
                          ナレッジから追加
                        </Button>
                      </div>
                    </div>
                  </div>
                  <div className='flex flex-col gap-2 border-t border-solid-gray-200 pt-3'>
                    <p className='text-dns-14N-130 text-solid-gray-700'>MCP</p>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      対話中にその場で参照します。ノートの参考資料には入りません。
                    </p>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      className='w-fit'
                      onClick={() => setSessionMcpOpen(true)}
                    >
                      このノートのMCP
                      {connectedMcps.length > 0 ? `（On ${enabledMcpCount}）` : ''}
                    </Button>
                  </div>
                </div>
                {sourceCount === 0 ? (
                  <p className='text-dns-14N-130 text-solid-gray-600'>未追加です。</p>
                ) : (
                  <div className='flex flex-col gap-2'>
                    {detail.files.map((f) => (
                      <SourceCard
                        key={`file-${f.id}`}
                        kind='ファイル'
                        name={f.filename}
                        nodeCount={f.node_count}
                        error={f.error}
                        briefing={f.briefing}
                        onDelete={() => void onDeleteFile(f.id)}
                      />
                    ))}
                    {(detail.knowledge_refs ?? []).map((ref) => (
                      <SourceCard
                        key={`knowledge-${ref.id}`}
                        kind='ナレッジ'
                        name={ref.title || ref.source}
                        nodeCount={ref.node_count}
                        briefing={ref.briefing}
                        onDelete={() => void onDeleteKnowledge(ref.id)}
                      />
                    ))}
                  </div>
                )}
              </section>
            )}

            {pane === 'chat' && detail && (
              <div className='flex min-h-0 flex-1 flex-col gap-3'>
                <NotebookChat
                  messages={detail.messages ?? []}
                  items={detail.items ?? []}
                  skills={skills}
                  skillId={skillId}
                  applyItemId={applyItemId}
                  draft={chatDraft}
                  submitting={actions.submitting}
                  llmEnabled={llmEnabled}
                  onSkillIdChange={setSkillId}
                  onApplyItemIdChange={setApplyItemId}
                  onDraftChange={setChatDraft}
                  onSend={() => void onChat()}
                  onApplyMessage={(m) => void onChatToItem(m)}
                />
              </div>
            )}

            {pane === 'items' && detail && (
              <div className='flex flex-col gap-3'>
                <div className='flex items-center justify-between gap-2'>
                  <h2 className='text-std-18B-160'>項目</h2>
                  <Button type='button' variant='outline' size='sm' onClick={() => void onAddItem()}>
                    項目を追加
                  </Button>
                </div>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  項目名が設問です。生成は参考資料の該当節だけを根拠にします。
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
                        <div className='flex flex-col gap-2'>
                          {!!draft.value.trim() && (
                            <div className='flex justify-end'>
                              <Button
                                type='button'
                                variant='outline'
                                size='xs'
                                onClick={() => {
                                  void onSaveItem(item.id, 'value');
                                  setEditingValueId(null);
                                }}
                              >
                                表示に戻す
                              </Button>
                            </div>
                          )}
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
                            onBlur={() => void onSaveItem(item.id, 'value')}
                          />
                        </div>
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

                <div className='flex flex-col gap-2'>
                  <Label htmlFor='notebook-instruction'>生成指示</Label>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    ヒアリングシート内に、Markdown エディタで処理させる指示を埋め込むことができます。
                  </p>
                  <Textarea
                    id='notebook-instruction'
                    rows={4}
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onBlur={() => void onSaveInstruction()}
                  />
                </div>

                <div className='flex flex-wrap gap-2'>
                  <Button type='button' variant='solid-fill' size='md' onClick={() => void onDownloadFilled()}>
                    記入済みシートをダウンロード
                  </Button>
                  <Button type='button' variant='outline' size='md' onClick={() => void onDeleteSession()}>
                    このノートを削除
                  </Button>
                </div>
              </div>
            )}

            {(actions.error || downloadError) && (
              <p className='text-std-16N-170 text-error-1' role='alert'>
                {actions.error || downloadError}
              </p>
            )}
          </>
        )}
      </div>

      <CustomDialog isOpen={sessionMcpOpen} onClose={() => setSessionMcpOpen(false)}>
        <CustomDialogPanel className='max-w-xl'>
          <CustomDialogHeader hasClose onClose={() => setSessionMcpOpen(false)}>
            このノートのMCP
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='mb-3 text-dns-14N-130 text-solid-gray-600'>
              対話中にその場で参照します。ノートの参考資料には入りません。接続の追加・切り離しとプロンプトは「AIタイプとMCP」から行います。
            </p>
            {connectedMcps.length === 0 ? (
              <p className='text-dns-14N-130 text-solid-gray-600'>
                接続中の MCP がありません。「AIタイプとMCP」から接続してください。
              </p>
            ) : (
              <ul className='flex flex-col gap-2'>
                {connectedMcps.map((m) => (
                  <li
                    key={m.id}
                    className='flex flex-col gap-1 rounded-8 border border-solid-gray-200 px-3 py-2 sm:flex-row sm:items-center sm:justify-between'
                  >
                    <div>
                      <p className='text-std-16B-150 text-solid-gray-900'>{m.name}</p>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        {m.catalog_id === 'knowledge'
                          ? '共有ナレッジ（共通チーム）を対話中に検索します。'
                          : m.description}
                      </p>
                    </div>
                    <Switch
                      checked={!!m.enabled}
                      label={m.enabled ? 'On' : 'Off'}
                      onSwitch={(next) => void onToggleSessionMcp(m.id, next)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>

      <NotebookManageDialog
        open={manageOpen}
        skills={skills}
        mcps={mcps}
        submitting={actions.submitting}
        onClose={() => setManageOpen(false)}
        onCreate={onCreateSkill}
        onDelete={onDeleteSkill}
        onUpdateMcp={onUpdateMcp}
        onCreateMcp={onCreateMcp}
        onDeleteMcp={onDeleteMcp}
      />

      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-xl'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            <div className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
              <p>・「ノート一覧」でノートを作り、開きます。</p>
              <p>・「参考資料」にファイルやナレッジを取り込みます。項目の根拠になります。</p>
              <p>・「参考資料を追加」の「このノートのMCP」で、対話中に使う MCP を On/Off します。</p>
              <p>・共有ナレッジ MCP は共通チームのナレッジをその場で検索します（取り込みではありません）。</p>
              <p>・「対話」で質問や整理をします。調べた手順は回答の上に出ます。</p>
              <p>・下書きを「項目に追加」すると、シートの正本になります。</p>
              <p>・「項目」で設問を直し、記入済みシートを Markdown エディタへ渡せます。</p>
              <p>・MCP の接続・切り離しとプロンプトは「AIタイプとMCP」から行います。</p>
              {config?.llm?.model && <p>・利用モデル: {config.llm.model}</p>}
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};
