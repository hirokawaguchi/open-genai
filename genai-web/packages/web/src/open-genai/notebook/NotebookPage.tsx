import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { PiBookOpenBold, PiFilePlus, PiPuzzlePieceBold } from 'react-icons/pi';
import { useLocation, useNavigate } from 'react-router';
import useSWR from 'swr';
import { Markdown } from '@/components/Markdown';
import { PageTitle } from '@/components/PageTitle';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Textarea } from '@/components/ui/dads/Textarea';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { NOTEBOOK_EXAPP_ID } from '@/layout/navItems';
import { ApiError } from '@/lib/fetcher';
import { KnowledgeSelectDialog } from '@/features/chat/components/KnowledgeSelectDialog';
import type { KnowledgePick } from '@/features/chat/stores/useChatStore';
import { listDocs, listTags, useScopes } from '@/open-genai/knowledge/useKnowledge';
import type { KnowledgeDoc } from '@/open-genai/knowledge/types';
import {
  fetchGeneration,
} from '@/open-genai/procuretech-editor/useProcuretechEditor';
import { newId } from '@/utils/uuid';
import { SourceList } from './Citations';
import { formatNotebookMarkdown } from './formatMarkdown';
import { NotebookChat } from './NotebookChat';
import { NotebookManageDialog } from './NotebookManageDialog';
import type {
  NotebookBriefing,
  NotebookFile,
  NotebookKnowledgeRef,
  NotebookSessionDetail,
} from './types';
import {
  fileToBase64,
  openNotebookInEditor,
  useNotebookActions,
  useNotebookConfig,
  useNotebookMcps,
  useNotebookSession,
  useNotebookSessions,
} from './useNotebook';

const PANE_TABS = [
  { id: 'list' as const, label: 'ノート一覧' },
  { id: 'chat' as const, label: 'エージェント' },
  { id: 'sources' as const, label: '参考資料' },
  { id: 'items' as const, label: '項目' },
  { id: 'editor' as const, label: 'Markdownエディタで編集' },
];

type NotebookPane = (typeof PANE_TABS)[number]['id'];

const NOTEBOOK_VIEW_KEY = 'notebook-last-view';

const readNotebookView = (): { sessionId: string | null; pane: NotebookPane } => {
  try {
    const raw = sessionStorage.getItem(NOTEBOOK_VIEW_KEY);
    if (!raw) return { sessionId: null, pane: 'list' };
    const parsed = JSON.parse(raw) as { sessionId?: unknown; pane?: unknown };
    const pane = PANE_TABS.some((tab) => tab.id === parsed.pane)
      ? (parsed.pane as NotebookPane)
      : 'list';
    const sessionId =
      typeof parsed.sessionId === 'string' && parsed.sessionId ? parsed.sessionId : null;
    if (pane !== 'list' && !sessionId) return { sessionId: null, pane: 'list' };
    return { sessionId, pane };
  } catch {
    return { sessionId: null, pane: 'list' };
  }
};

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

const fileProblem = (error?: string | null) => {
  const text = (error ?? '').trim();
  if (!text) return null;
  if (/file is not a zip file/i.test(text)) {
    return 'このファイルを読み取れませんでした。パスワードが掛かっているか、壊れているか、拡張子と中身が違う可能性があります。';
  }
  return text;
};

const SourcePiiWarning = ({ briefing }: { briefing?: NotebookBriefing }) => {
  const pii = briefing?.pii;
  if (!pii?.warned) return null;
  const hits = pii.hits ?? [];
  const lines = (pii.message || '').split('\n').filter(Boolean);
  return (
    <div className='mt-2 text-dns-14N-130 text-orange-800 whitespace-pre-wrap'>
      <p>＊{lines[0] || `個人情報の可能性: ${(pii.categories ?? []).join('・')}`}</p>
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

const FileSourceCard = ({ file, onDelete }: { file: NotebookFile; onDelete: () => void }) => {
  const problem = fileProblem(file.error);
  const briefing = file.briefing;
  const reading = briefing?.ingest === 'processing';
  let status = '読み取りました。';
  if (problem) status = '';
  else if (reading && briefing?.ocr_pending) status = 'スキャン画像を読み取っています。';
  else if (reading) status = '本文を読み取っています。';
  else if (briefing?.ocr) status = 'スキャンを OCR で読み取りました。';
  return (
    <article className='rounded-8 border border-solid-gray-300 px-3 py-3'>
      <div className='flex items-start justify-between gap-3'>
        <div className='min-w-0'>
          <p className='break-all text-std-16N-170 text-solid-gray-900'>{file.filename}</p>
          {status && (
            <p className='mt-1 flex items-center gap-2 text-dns-14N-130 text-solid-gray-600'>
              {reading && <Spinner />}
              {status}
            </p>
          )}
          {problem && <p className='mt-1 text-dns-14N-130 text-error-1'>{problem}</p>}
          <SourcePiiWarning briefing={briefing} />
        </div>
        <Button type='button' variant='outline' size='sm' className='shrink-0' onClick={onDelete}>
          削除
        </Button>
      </div>
    </article>
  );
};

const TagAccordion = ({
  title,
  count,
  description,
  children,
}: {
  title: string;
  count: number;
  description?: string;
  children: ReactNode;
}) => (
  <details className='tag-accordion rounded-8 border border-solid-gray-300'>
    <summary className='flex cursor-pointer list-none items-start gap-2 px-3 py-3 hover:bg-solid-gray-50 [&::-webkit-details-marker]:hidden'>
      <svg
        aria-hidden={true}
        className='tag-accordion-mark mt-1 size-4 shrink-0 text-blue-900'
        viewBox='0 0 16 16'
        fill='none'
      >
        <path
          d='M3.5 6 L8 10.5 L12.5 6'
          stroke='currentColor'
          strokeWidth='1.5'
          strokeLinecap='round'
          strokeLinejoin='round'
        />
      </svg>
      <span className='min-w-0 flex-1'>
        <span className='block break-all text-std-16N-170 text-solid-gray-900'>{title}</span>
        {description && (
          <span className='mt-1 block text-dns-14N-130 text-solid-gray-700'>{description}</span>
        )}
      </span>
      <span className='shrink-0 text-dns-14N-130 text-solid-gray-700'>{count}件</span>
    </summary>
    {children}
  </details>
);

const KnowledgeSourceList = ({
  refs,
  sharedScope,
  sharedDocs,
}: {
  refs: NotebookKnowledgeRef[];
  /** MCP の共有ナレッジが On のとき。このスコープの文書はすべて対象として出す。 */
  sharedScope?: { scope: string; name: string } | null;
  sharedDocs?: KnowledgeDoc[] | null;
}) => {
  const { scopes } = useScopes();
  const listedRefs = useMemo(
    () => (sharedScope ? refs.filter((ref) => ref.scope !== sharedScope.scope) : refs),
    [refs, sharedScope],
  );
  const scopeIds = useMemo(() => {
    const ids = new Set(listedRefs.map((ref) => ref.scope));
    if (sharedScope) ids.add(sharedScope.scope);
    return [...ids].sort();
  }, [listedRefs, sharedScope]);
  const fetchIds = useMemo(
    () => scopeIds.filter((id) => id !== sharedScope?.scope),
    [scopeIds, sharedScope],
  );
  const fetchKey = fetchIds.join('\u0000');
  const { data, error, isLoading } = useSWR(
    fetchIds.length ? (['notebook-source-docs', fetchKey] as const) : null,
    async ([, joined]) => {
      const ids = joined.split('\u0000').filter(Boolean);
      const pairs = await Promise.all(
        ids.map(async (scope) => [scope, await listDocs(scope)] as const),
      );
      return new Map(pairs);
    },
  );
  // タグ説明はナレッジ管理で後から変わる。開いている参考資料が保存前の一覧を持ったままにならないよう、表示のたびに取り直す。
  const [tagLists, setTagLists] = useState<Map<string, Awaited<ReturnType<typeof listTags>>> | null>(
    null,
  );
  useEffect(() => {
    if (!scopeIds.length) {
      setTagLists(new Map());
      return;
    }
    let cancelled = false;
    const load = () => {
      void Promise.all(
        scopeIds.map(async (scope) => [scope, await listTags(scope)] as const),
      ).then((pairs) => {
        if (!cancelled) setTagLists(new Map(pairs));
      });
    };
    load();
    window.addEventListener('focus', load);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', load);
    };
  }, [scopeIds]);
  const scopeName = (scope: string) =>
    scopes.find((item) => item.scope === scope)?.name ||
    (scope === sharedScope?.scope ? sharedScope.name : '');
  const teams = useMemo(() => {
    const waitingForShared = Boolean(sharedScope) && sharedDocs == null;
    const waitingForRefs = fetchIds.length > 0 && !data;
    if (waitingForShared || waitingForRefs) return null;
    const docsByScope = new Map(data ?? []);
    if (sharedScope && sharedDocs) docsByScope.set(sharedScope.scope, sharedDocs);
    const tagsOf = new Map<string, string[]>();
    for (const [scope, docs] of docsByScope) {
      for (const doc of docs) {
        tagsOf.set(`${scope}\u0000${doc.doc_id}`, (doc.tags ?? []).filter(Boolean));
      }
    }
    const descriptions = new Map<string, string>();
    for (const [scope, tags] of tagLists ?? []) {
      for (const tag of tags) {
        descriptions.set(`${scope}\u0000${tag.tag}`, (tag.description ?? '').trim());
      }
    }
    const byScope = new Map<
      string,
      {
        scope: string;
        tags: Map<string, { tag: string; description: string; refs: NotebookKnowledgeRef[] }>;
        untagged: NotebookKnowledgeRef[];
      }
    >();
    const teamOf = (scope: string) => {
      const current = byScope.get(scope);
      if (current) return current;
      const created = { scope, tags: new Map(), untagged: [] as NotebookKnowledgeRef[] };
      byScope.set(scope, created);
      return created;
    };
    const place = (ref: NotebookKnowledgeRef, tags: string[]) => {
      const team = teamOf(ref.scope);
      if (tags.length === 0) {
        team.untagged.push(ref);
        return;
      }
      for (const tag of tags) {
        const key = `${ref.scope}\u0000${tag}`;
        const group = team.tags.get(tag) ?? {
          tag,
          description: descriptions.get(key) ?? '',
          refs: [],
        };
        group.description = descriptions.get(key) ?? group.description;
        group.refs.push(ref);
        team.tags.set(tag, group);
      }
    };
    for (const ref of listedRefs) {
      place(ref, tagsOf.get(`${ref.scope}\u0000${ref.doc_id}`) ?? []);
    }
    if (sharedScope && sharedDocs) {
      for (const doc of sharedDocs) {
        if (doc.ingest_status === 'failed') continue;
        place(
          {
            id: `shared-${doc.doc_id}`,
            scope: sharedScope.scope,
            doc_id: doc.doc_id,
            source: doc.source,
            title: doc.source,
            created_at: '',
          },
          (doc.tags ?? []).map((tag) => tag.trim()).filter(Boolean),
        );
      }
    }
    return [...byScope.values()]
      .map((team) => ({
        scope: team.scope,
        name: scopeName(team.scope) || team.scope,
        common: scopes.find((item) => item.scope === team.scope)?.kind === 'common',
        tags: [...team.tags.values()].sort((a, b) => a.tag.localeCompare(b.tag, 'ja')),
        untagged: team.untagged,
      }))
      .filter((team) => team.tags.length > 0 || team.untagged.length > 0)
      .sort((a, b) => {
        if (a.common !== b.common) return a.common ? -1 : 1;
        return a.name.localeCompare(b.name, 'ja');
      });
  }, [data, fetchIds.length, listedRefs, scopes, sharedDocs, sharedScope, tagLists]);

  const waiting = (Boolean(sharedScope) && sharedDocs == null) || (fetchIds.length > 0 && isLoading);
  if (error || !teams) {
    return (
      <p className='text-dns-14N-130 text-solid-gray-600'>
        {error || !waiting ? 'タグ名を読み込めませんでした。' : 'タグを読み込んでいます。'}
      </p>
    );
  }

  return (
    <div className='flex flex-col gap-6'>
      <style>{`
        .tag-accordion > summary > .tag-accordion-mark { transition: transform 150ms ease; }
        .tag-accordion[open] > summary > .tag-accordion-mark { transform: rotate(180deg); }
      `}</style>
      {teams.map((team) => (
        <section key={team.scope} className='flex flex-col gap-2'>
          <h4 className='text-std-16B-150 text-solid-gray-900'>{team.name}</h4>
          {team.tags.map((group) => (
            <TagAccordion
              key={`${team.scope}\u0000${group.tag}`}
              title={group.tag}
              count={group.refs.length}
              description={group.description}
            >
              <ul className='flex flex-col gap-1 border-t border-solid-gray-200 px-3 py-3 pl-9'>
                {group.refs.map((ref) => (
                  <li key={ref.id} className='break-all text-dns-14N-130 text-solid-gray-800'>
                    {ref.title || ref.source}
                  </li>
                ))}
              </ul>
            </TagAccordion>
          ))}
          {team.untagged.length > 0 && (
            <TagAccordion title='タグが付いていません' count={team.untagged.length}>
              <ul className='flex flex-col gap-1 border-t border-solid-gray-200 px-3 py-3 pl-9'>
                {team.untagged.map((ref) => (
                  <li key={ref.id} className='break-all text-dns-14N-130 text-solid-gray-800'>
                    {ref.title || ref.source}
                  </li>
                ))}
              </ul>
            </TagAccordion>
          )}
        </section>
      ))}
    </div>
  );
};

const UnavailableNotice = ({ message }: { message?: string }) => (
  <div
    className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
    role='status'
  >
    <p className='text-std-16B-150 text-solid-gray-900'>ノートブックに接続できません</p>
    <p className='mt-2 text-solid-gray-700'>
      {message || '`docker compose up -d` でサービスを起動してください。'}
    </p>
    <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
      docker compose up -d --build
    </pre>
  </div>
);

export const NotebookPage = () => {
  const { documentTitle, howToUse, title, description } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    NOTEBOOK_EXAPP_ID,
    'ノートブック',
    '参考資料を集めて調べ、項目として整理します。Markdown エディタの編集画面へ渡せます。',
  );
  const { config, isLoading: configLoading, unavailable } = useNotebookConfig();
  const { sessions, mutate: mutateSessions } = useNotebookSessions();
  const location = useLocation();
  const [sessionId, setSessionId] = useState<string | null>(() => readNotebookView().sessionId);
  const { detail, loadError, mutate: mutateDetail } = useNotebookSession(sessionId);
  const { mcps, mutate: mutateMcps } = useNotebookMcps();
  const actions = useNotebookActions();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const openRun = useRef(0);
  const [listTitles, setListTitles] = useState<Record<string, string>>({});
  const [newNoteName, setNewNoteName] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { label: string; value: string }>>({});
  const [openError, setOpenError] = useState<string | null>(null);
  const [openingEditor, setOpeningEditor] = useState(false);
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const [pane, setPane] = useState<NotebookPane>(() => readNotebookView().pane);
  useEffect(() => {
    const handed = (location.state as { sessionId?: string } | null)?.sessionId;
    if (handed) {
      setSessionId(handed);
      setPane('chat');
    }
  }, [location.state]);
  useEffect(() => {
    const view =
      pane === 'list' || !sessionId
        ? { sessionId: null, pane: 'list' as const }
        : { sessionId, pane };
    sessionStorage.setItem(NOTEBOOK_VIEW_KEY, JSON.stringify(view));
  }, [sessionId, pane]);
  useEffect(() => {
    if (!sessionId || loadError !== '見つかりません') return;
    setSessionId(null);
    setPane('list');
  }, [sessionId, loadError]);
  const [helpOpen, setHelpOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [chatDraft, setChatDraft] = useState('');
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [knowledgePicks, setKnowledgePicks] = useState<KnowledgePick[]>([]);
  const [addingKnowledge, setAddingKnowledge] = useState(false);
  const [addingKnowledgeLabel, setAddingKnowledgeLabel] = useState('');
  const [editingValueId, setEditingValueId] = useState<string | null>(null);
  const [addingFiles, setAddingFiles] = useState(false);
  const [addingFileLabel, setAddingFileLabel] = useState('');
  const [sourceNotice, setSourceNotice] = useState<string | null>(null);
  const sourceNoticeTimer = useRef<number | null>(null);
  const knowledgePicksRef = useRef<KnowledgePick[]>([]);
  const knowledgeSync = useRef(Promise.resolve());
  const detailRef = useRef(detail);
  detailRef.current = detail;

  useEffect(() => {
    setPendingProjectId(null);
    setOpenError(null);
    knowledgePicksRef.current = [];
    setKnowledgePicks([]);
  }, [sessionId]);

  useEffect(
    () => () => {
      openRun.current += 1;
      if (sourceNoticeTimer.current !== null) window.clearTimeout(sourceNoticeTimer.current);
    },
    [],
  );

  const showSourceNotice = (text: string) => {
    setSourceNotice(text);
    if (sourceNoticeTimer.current !== null) window.clearTimeout(sourceNoticeTimer.current);
    sourceNoticeTimer.current = window.setTimeout(() => {
      setSourceNotice(null);
      sourceNoticeTimer.current = null;
    }, 5000);
  };

  useEffect(() => {
    if (!detail) return;
    setDrafts(
      Object.fromEntries(detail.items.map((i) => [i.id, { label: i.label, value: i.value }])),
    );
  }, [detail]);

  // 読み取り中の資料がある間だけ短い間隔で取り直す。件数は読み取り完了後に増える。
  // 編集中は差し替えない（下書きを消さない）。
  const ingestPending = useMemo(
    () =>
      (detail?.files ?? []).some(
        (f) => f.briefing?.ingest === 'processing' || f.briefing?.ocr_pending,
      ),
    [detail],
  );
  useEffect(() => {
    if (!ingestPending || !sessionId) return;
    const timer = window.setInterval(() => {
      if (editingValueId !== null) return;
      void mutateDetail();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [ingestPending, sessionId, editingValueId, detail, mutateDetail]);

  useEffect(() => {
    const root = document.getElementById('layoutRoot');
    const main = document.getElementById('mainContents');
    const column = main?.parentElement ?? null;
    const row = column?.parentElement ?? null;
    const html = document.documentElement;
    const prevHtmlOverflow = html.style.overflow;
    const prevRootHeight = root?.style.height ?? '';
    const prevRootOverflow = root?.style.overflow ?? '';
    html.style.overflow = 'hidden';
    if (root) {
      root.style.height = '100dvh';
      root.style.overflow = 'hidden';
    }
    const added: Array<[HTMLElement, string[]]> = [];
    const add = (el: HTMLElement | null, classes: string[]) => {
      if (!el) return;
      const next = classes.filter((name) => !el.classList.contains(name));
      if (next.length === 0) return;
      el.classList.add(...next);
      added.push([el, next]);
    };
    // サイドメニューと同じ行に overflow を付けると、sticky の基準が行になり、
    // メニューがヘッダーの高さぶん下がる。縮むのは中の列だけにする。
    add(row, ['min-h-0']);
    add(column, ['min-h-0', 'overflow-hidden']);
    add(main, ['flex', 'min-h-0', 'flex-col', 'overflow-hidden']);
    const shell = document.getElementById('notebook-shell');
    let node = shell?.parentElement ?? null;
    while (node && node !== main) {
      add(node, ['flex', 'min-h-0', 'h-full', 'flex-1', 'flex-col', 'overflow-hidden']);
      node = node.parentElement;
    }
    return () => {
      html.style.overflow = prevHtmlOverflow;
      if (root) {
        root.style.height = prevRootHeight;
        root.style.overflow = prevRootOverflow;
      }
      for (const [el, classes] of added) {
        el.classList.remove(...classes);
      }
    };
  }, [pane]);

  const accept = (
    config?.accept ?? ['.pdf', '.docx', '.xlsx', '.pptx', '.txt', '.md', '.csv', '.html', '.json']
  ).join(',');
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
    setOpenError(null);
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
        setAddingFileLabel(list.length > 1 ? `${file.name}（${i + 1}/${list.length}）` : file.name);
        const content = await fileToBase64(file);
        latest = (await actions.addFile(sessionId, file.name, content)) ?? latest;
        if (latest) await refresh(latest);
      }
      if (fileRef.current) fileRef.current.value = '';
    } finally {
      setAddingFiles(false);
      setAddingFileLabel('');
    }
  };

  const onDeleteFile = async (fileId: string) => {
    if (!sessionId) return;
    if (!window.confirm('このファイルを参考資料から外しますか？')) return;
    const next = await actions.deleteFile(sessionId, fileId);
    if (next) await refresh(next);
  };

  const pickKey = (pick: KnowledgePick) => `${pick.scope}\u0000${pick.tag}`;

  const docsForPicks = async (picks: KnowledgePick[]) => {
    const docs: KnowledgeDoc[] = [];
    for (const pick of picks) {
      const listed = await listDocs(pick.scope, [pick.tag]);
      for (const doc of listed) {
        docs.push({ ...doc, scope: doc.scope || pick.scope });
      }
    }
    return docs;
  };

  const applyKnowledgeChange = async (
    session: string,
    prev: KnowledgePick[],
    nextPicks: KnowledgePick[],
  ) => {
    const prevKeys = new Set(prev.map(pickKey));
    const nextKeys = new Set(nextPicks.map(pickKey));
    const added = nextPicks.filter((pick) => !prevKeys.has(pickKey(pick)));
    const removed = prev.filter((pick) => !nextKeys.has(pickKey(pick)));
    if (added.length === 0 && removed.length === 0) return;

    setAddingKnowledge(true);
    try {
      let latest = detailRef.current;
      if (added.length > 0) {
        const pendingNotes: string[] = [];
        const toAdd: { scope: string; doc_id: string; source: string }[] = [];
        const existing = new Set(
          (latest?.knowledge_refs ?? []).map((ref) => `${ref.scope}\u0000${ref.doc_id}`),
        );
        for (const pick of added) {
          let docs: KnowledgeDoc[] = [];
          try {
            docs = await listDocs(pick.scope, [pick.tag]);
          } catch {
            actions.setError('ナレッジの文書を読み込めませんでした。');
            continue;
          }
          const pending = docs.filter(
            (doc) => doc.ingest_status === 'queued' || doc.ingest_status === 'processing',
          );
          const ready = docs.filter(
            (doc) =>
              doc.ingest_status !== 'failed' &&
              doc.ingest_status !== 'queued' &&
              doc.ingest_status !== 'processing',
          );
          if (pending.length > 0) {
            pendingNotes.push(`${pick.tag} は処理中が ${pending.length} 件あります。`);
          }
          if (ready.length === 0 && pending.length === 0) {
            actions.setError(
              docs.length > 0
                ? `${pick.tag} の文書は取り込みに失敗しているため、追加できません。`
                : `${pick.tag} が付いた文書はありません。`,
            );
          }
          for (const doc of ready) {
            const key = `${pick.scope}\u0000${doc.doc_id}`;
            if (existing.has(key)) continue;
            existing.add(key);
            toAdd.push({ scope: pick.scope, doc_id: doc.doc_id, source: doc.source });
          }
        }
        if (toAdd.length > 0) {
          const imported = await actions.addKnowledgeRefs(session, toAdd, setAddingKnowledgeLabel);
          if (imported) {
            latest = imported;
            detailRef.current = imported;
            await refresh(imported);
            showSourceNotice('参考資料に登録しました');
          }
        }
        if (pendingNotes.length > 0) {
          actions.setError(
            `${pendingNotes.join('')} 終わってから、同じタグをもう一度選んでください。`,
          );
        }
      }
      if (removed.length > 0) {
        let removeDocs: KnowledgeDoc[] = [];
        let keepDocs: KnowledgeDoc[] = [];
        try {
          removeDocs = await docsForPicks(removed);
          keepDocs = await docsForPicks(nextPicks);
        } catch {
          actions.setError('ナレッジの文書を読み込めませんでした。');
          return;
        }
        const removeIds = new Set(removeDocs.map((doc) => `${doc.scope}\u0000${doc.doc_id}`));
        const keepIds = new Set(keepDocs.map((doc) => `${doc.scope}\u0000${doc.doc_id}`));
        const refs = (latest?.knowledge_refs ?? detailRef.current?.knowledge_refs ?? []).filter(
          (ref) => {
            const key = `${ref.scope}\u0000${ref.doc_id}`;
            return removeIds.has(key) && !keepIds.has(key);
          },
        );
        for (const ref of refs) {
          const deleted = await actions.deleteKnowledgeRef(session, ref.id);
          if (deleted) {
            latest = deleted;
            detailRef.current = deleted;
            await refresh(deleted);
          }
        }
      }
    } finally {
      setAddingKnowledge(false);
      setAddingKnowledgeLabel('');
    }
  };

  const onKnowledgePicks = (nextPicks: KnowledgePick[]) => {
    const prev = knowledgePicksRef.current;
    knowledgePicksRef.current = nextPicks;
    setKnowledgePicks(nextPicks);
    if (!sessionId) return;
    const session = sessionId;
    knowledgeSync.current = knowledgeSync.current
      .then(() => applyKnowledgeChange(session, prev, nextPicks))
      .catch(() => undefined);
  };

  const onRetry = async () => {
    if (!sessionId || !detail) return;
    const messages = detail.messages ?? [];
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'assistant') return;
    const prev = detail;
    await mutateDetail(
      {
        ...detail,
        messages: messages.map((message, index) =>
          index === messages.length - 1
            ? { ...message, content: ' ', tool_trace: [], citations: [] }
            : message,
        ),
      },
      { revalidate: false },
    );
    const next = await actions.retryChat(sessionId);
    if (next) {
      await refresh(next);
      return;
    }
    await mutateDetail(prev, { revalidate: false });
  };

  const onChat = async () => {
    if (!sessionId || !chatDraft.trim()) return;
    const q = chatDraft.trim();
    const prev = detail;
    const localId = `local-${newId()}`;
    setChatDraft('');
    if (detail) {
      await mutateDetail(
        {
          ...detail,
          messages: [
            ...(detail.messages ?? []),
            {
              id: localId,
              role: 'user',
              content: q,
              created_at: new Date().toISOString(),
            },
          ],
        },
        { revalidate: false },
      );
    }
    const next = await actions.chat(sessionId, q);
    if (next) {
      await refresh(next);
      const last = [...(next.messages ?? [])].reverse().find((m) => m.role === 'assistant');
      if (last?.open_editor) {
        setPane('editor');
        void onOpenEditor(next);
      }
      return;
    }
    setChatDraft(q);
    if (prev) await mutateDetail(prev, { revalidate: false });
    else await mutateDetail();
  };

  const onUpdateMcp = async (
    id: string,
    body: { connected?: boolean; prompt?: string; reset_prompt?: boolean },
  ) => {
    const next = await actions.updateMcp(id, body);
    if (!next) return false;
    await mutateMcps();
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

  const flushDrafts = async () => {
    if (!sessionId || !detail) return;
    for (const item of detail.items) {
      const draft = drafts[item.id];
      if (!draft) continue;
      if (draft.label === item.label && draft.value === item.value) continue;
      const next = await actions.updateItem(sessionId, item.id, {
        label: draft.label,
        value: draft.value,
      });
      if (next) await refresh(next);
    }
  };

  const onOpenEditor = async (source?: NotebookSessionDetail) => {
    const current = source ?? detail;
    if (!sessionId || !current || openingEditor) return;
    const run = openRun.current + 1;
    openRun.current = run;
    setOpenError(null);
    setPendingProjectId(null);
    setOpeningEditor(true);
    try {
      await flushDrafts();
      if (openRun.current !== run) return;
      const projectId = current.editor_project_id?.trim() ?? '';
      const started = await openNotebookInEditor(sessionId, {
        mode: projectId ? 'existing' : 'new',
        name: projectId ? undefined : current.title,
        project_id: projectId || undefined,
      });
      if (!projectId) {
        await actions.updateSession(sessionId, { editor_project_id: started.project_id });
      }
      const deadline = Date.now() + 5 * 60 * 1000;
      let status = await fetchGeneration(started.project_id, started.request_id);
      while (status.status !== 'success' && status.status !== 'error') {
        if (openRun.current !== run) return;
        if (Date.now() > deadline) {
          setPendingProjectId(started.project_id);
          setOpenError('章の作成が時間内に終わりませんでした。作成したプロジェクトは開けます。');
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        if (openRun.current !== run) return;
        status = await fetchGeneration(started.project_id, started.request_id);
      }
      if (status.status === 'error') {
        setPendingProjectId(started.project_id);
        setOpenError(status.error || '章の作成に失敗しました。');
        return;
      }
      navigate(`/procuretech-editor?project=${encodeURIComponent(started.project_id)}`);
    } catch (e) {
      if (openRun.current !== run) return;
      const data =
        e instanceof ApiError ? (e.data as { error?: string; project_id?: string }) : undefined;
      if (data?.project_id) setPendingProjectId(data.project_id);
      setOpenError(data?.error || '編集画面を開けませんでした。');
    } finally {
      if (openRun.current === run) setOpeningEditor(false);
    }
  };

  const fileSettled = (file: { briefing?: { ingest?: string } }) =>
    file.briefing?.ingest !== 'processing';
  const fileNotices = useMemo(
    () =>
      (detail?.files ?? []).flatMap((file) => {
        const pii = file.briefing?.pii;
        if (!pii?.warned) return [];
        return [
          {
            id: file.id,
            filename: file.filename,
            message: pii.message,
            categories: pii.categories,
            hits: pii.hits,
          },
        ];
      }),
    [detail],
  );
  const sharedKnowledgeViaMcp = mcps.some(
    (mcp) => mcp.catalog_id === 'knowledge' && mcp.connected && mcp.available,
  );
  const { scopes } = useScopes();
  const commonScope = scopes.find((item) => item.kind === 'common') ?? null;
  const sharedScope =
    sharedKnowledgeViaMcp && commonScope
      ? { scope: commonScope.scope, name: commonScope.name }
      : null;
  const { data: sharedDocs } = useSWR(
    sharedScope ? (['notebook-shared-docs', sharedScope.scope] as const) : null,
    ([, scope]) => listDocs(scope),
  );
  const sharedDocCount = (sharedDocs ?? []).filter((doc) => doc.ingest_status !== 'failed').length;
  const registeredRefs = (detail?.knowledge_refs ?? []).filter(
    (ref) => !(sharedDocs && sharedScope && ref.scope === sharedScope.scope),
  );
  const sourceCount =
    (detail?.files.filter(fileSettled).length ?? 0) + registeredRefs.length + sharedDocCount;
  const sharedPending = Boolean(sharedScope) && sharedDocs == null;
  const listedSourceCount =
    (detail?.files.length ?? 0) + registeredRefs.length + sharedDocCount;
  const webSearchMcp = mcps.find((mcp) => mcp.catalog_id === 'firecrawl');
  const webSearchOn = Boolean(webSearchMcp?.available && webSearchMcp.connected);
  const onWebSearch = (next: boolean) => {
    if (!webSearchMcp?.available) return;
    void onUpdateMcp(webSearchMcp.id, { connected: next });
  };
  const sending = actions.submitting && !addingFiles && !addingKnowledge;
  const maxUploadMb = Math.round((config?.max_upload_bytes ?? 20 * 1024 * 1024) / 1024 / 1024);

  const needNote = pane !== 'list' && !detail;
  const noteTitle = detail?.title?.trim() || 'ノート';
  const crumbs =
    pane !== 'list' && (detail || sessionId)
      ? [
          { label: 'ホーム', to: '/' },
          { label: title, onClick: () => setPane('list') },
          { label: noteTitle },
        ]
      : [
          { label: 'ホーム', to: '/' },
          { label: title },
        ];

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div
        id='notebook-shell'
        className='mx-auto flex min-h-0 w-full max-w-(--page-width) flex-1 flex-col overflow-hidden px-4 py-2 lg:px-6'
      >
        <div className='shrink-0'>
          <BreadcrumbsNav items={crumbs} />
          <div className='mt-1 flex min-w-0 items-center gap-3'>
            <div className='flex min-w-0 flex-1 items-center gap-3'>
              <h1 className='min-w-0 shrink-0 text-std-16B-170 text-solid-gray-900'>{title}</h1>
              {description && (
                <p
                  className='min-w-0 flex-1 truncate text-dns-14N-130 text-solid-gray-600'
                  title={description}
                >
                  {description}
                </p>
              )}
            </div>
            <div className='flex shrink-0 items-center gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                className='inline-flex items-center gap-1'
                onClick={() => setManageOpen(true)}
              >
                <PiPuzzlePieceBold aria-hidden={true} className='size-4' />
                MCP
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
        </div>

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <UnavailableNotice message={config?.error} />
        )}

        {!unavailable && (
          <>
            <div className='mt-3 shrink-0 overflow-x-auto border-b border-solid-gray-300'>
              <div className='flex w-max min-w-full gap-1'>
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
            </div>

            <div className='flex min-h-0 flex-1 flex-col'>
            {(actions.error || openError) && (
              <p className='shrink-0 py-2 text-std-16N-170 text-error-1' role='alert'>
                {actions.error || openError}
              </p>
            )}

            {pane === 'list' && (
              <section className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto py-4'>
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
                            <td className='px-3 py-2 text-solid-gray-600'>
                              {formatWhen(s.updated_at)}
                            </td>
                            <td className='px-3 py-2 text-solid-gray-600'>
                              {s.filled_count ?? 0}/{s.item_count ?? 0}
                            </td>
                            <td className='px-3 py-2 text-right'>
                              <div className='inline-flex gap-2'>
                                <Button
                                  type='button'
                                  variant='solid-fill'
                                  size='xs'
                                  onClick={() => onSelect(s.id)}
                                >
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
              <div className='my-4 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
                「ノート一覧」タブからノートを開いてください。
              </div>
            )}

            {pane === 'sources' && detail && (
              <section className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto py-4'>
                <h2 className='text-std-18B-160 text-solid-gray-900'>
                  参考資料（{sourceCount}件）
                </h2>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  いまこのノートの対象です。ファイルの添付と、チームのタグの選択は、エージェントの入力欄から行います。共有ナレッジの
                  MCP が On のあいだは、共有ナレッジの文書もすべて対象です。一部のタグだけにするには、MCP
                  を Off にしてからそのタグを登録します。いらないファイルは、ここから外せます。
                </p>
                {(addingFiles || addingKnowledge) && (
                  <p className='flex items-center gap-2 text-dns-14N-130 text-solid-gray-700'>
                    <Spinner />
                    {addingFileLabel
                      ? `${addingFileLabel} を取り込んでいます`
                      : addingKnowledgeLabel
                        ? `${addingKnowledgeLabel} を取り込んでいます`
                        : '参考資料を取り込んでいます'}
                  </p>
                )}
                {listedSourceCount === 0 && !sharedPending ? (
                  <p className='text-dns-14N-130 text-solid-gray-600'>まだありません。</p>
                ) : (
                  <div className='flex flex-col gap-6'>
                    {detail.files.length > 0 && (
                      <div className='flex flex-col gap-2'>
                        <h3 className='text-std-16B-150 text-solid-gray-900'>ファイル</h3>
                        {detail.files.map((file) => (
                          <FileSourceCard
                            key={file.id}
                            file={file}
                            onDelete={() => void onDeleteFile(file.id)}
                          />
                        ))}
                      </div>
                    )}
                    {(registeredRefs.length > 0 || sharedScope) && (
                      <div className='flex flex-col gap-2'>
                        <h3 className='text-std-16B-150 text-solid-gray-900'>ナレッジ</h3>
                        <KnowledgeSourceList
                          refs={detail.knowledge_refs ?? []}
                          sharedScope={sharedScope}
                          sharedDocs={sharedDocs ?? null}
                        />
                      </div>
                    )}
                  </div>
                )}
              </section>
            )}

            {pane === 'chat' && detail && (
              <div className='flex min-h-0 flex-1 flex-col gap-3'>
                <NotebookChat
                  messages={detail.messages ?? []}
                  draft={chatDraft}
                  submitting={sending}
                  liveSteps={actions.liveSteps}
                  llmEnabled={llmEnabled}
                  attaching={addingFiles}
                  knowledgeBusy={addingKnowledge}
                  uploadLimitMb={maxUploadMb}
                  notice={sourceNotice}
                  fileNotices={fileNotices}
                  webSearchOn={webSearchOn}
                  webSearchAvailable={Boolean(webSearchMcp?.available)}
                  onWebSearch={onWebSearch}
                  onAttach={() => fileRef.current?.click()}
                  onOpenKnowledge={() => setKnowledgeOpen(true)}
                  onDraftChange={setChatDraft}
                  onSend={() => void onChat()}
                  sessionId={sessionId}
                  onRetry={() => void onRetry()}
                />
              </div>
            )}

            {pane === 'items' && detail && (
              <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto py-4'>
                <div className='flex items-center justify-between gap-2'>
                  <h2 className='text-std-18B-160'>項目</h2>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={() => void onAddItem()}
                  >
                    項目を追加
                  </Button>
                </div>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  見出しが章の名前、本文が章の中身です。エージェントの下書きは、章ごとに項目にしてから正本になります。生成は参考資料の該当節だけを根拠にします。
                </p>
                <div className='flex flex-col gap-3 pb-2'>
                  {detail.items.length === 0 && (
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      「項目を追加」から章を増やしてください。
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
                          <Label htmlFor={`notebook-label-${item.id}`}>見出し {index + 1}</Label>
                          <div className='flex flex-wrap gap-2'>
                            <Button
                              type='button'
                              variant='solid-fill'
                              size='sm'
                              aria-disabled={
                                busy || !llmEnabled || !draft.label.trim() || undefined
                              }
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
                          placeholder='例: 背景'
                          value={draft.label}
                          onChange={(e) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [item.id]: { ...draft, label: e.target.value },
                            }))
                          }
                          onBlur={() => void onSaveItem(item.id, 'label')}
                        />
                        <Label htmlFor={`notebook-value-${item.id}`}>本文</Label>
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
                              placeholder='本文（手入力または生成）'
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
                </div>
              </div>
            )}

            {pane === 'editor' && detail && (
              <div className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto py-4'>
                <h2 className='text-std-18B-160'>Markdownエディタで編集</h2>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  エージェントで文書が揃うと、編集画面を開きます。章の手直しと書き出しは、開いたあとのエディタで行います。
                </p>
                {openingEditor && (
                  <p className='inline-flex items-center gap-2 text-dns-14N-130 text-solid-gray-700'>
                    <Spinner />
                    編集画面を開いています。
                  </p>
                )}
                {(pendingProjectId || detail.editor_project_id) && (
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    onClick={() => {
                      const projectId = pendingProjectId || detail.editor_project_id;
                      if (!projectId) return;
                      navigate(
                        `/procuretech-editor?project=${encodeURIComponent(projectId)}`,
                      );
                    }}
                  >
                    編集画面を開く
                  </Button>
                )}
              </div>
            )}
            </div>
          </>
        )}
      </div>

      <input
        ref={fileRef}
        type='file'
        multiple
        accept={accept}
        className='sr-only'
        onChange={(e) => void onPickFiles(e.target.files)}
      />
      <KnowledgeSelectDialog
        isOpen={knowledgeOpen}
        picks={knowledgePicks}
        onChange={onKnowledgePicks}
        onClose={() => setKnowledgeOpen(false)}
        description={
          sharedKnowledgeViaMcp
            ? 'チームのタグを選ぶと、その文書を参考資料に写します。共有ナレッジは MCP が On のため、すべてのタグが対象です。一部だけにするには、MCP を Off にしてからタグを登録します。'
            : 'タグを選ぶと、そのタグが付いた文書を参考資料に写します。チェックを外すと、その文書を参考資料から外します。'
        }
        sharedKnowledgeLocked={sharedKnowledgeViaMcp}
      />

      <NotebookManageDialog
        open={manageOpen}
        mcps={mcps}
        submitting={actions.submitting}
        onClose={() => setManageOpen(false)}
        onUpdateMcp={onUpdateMcp}
        onCreateMcp={onCreateMcp}
        onDeleteMcp={onDeleteMcp}
      />

      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            {howToUse ? (
              <ExAppUsageMarkdownRenderer content={howToUse} size='sm' />
            ) : (
              <div className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
                <p>・「ノート一覧」でノートを作り、開きます。</p>
                <p>
                  ・「エージェント」の入力欄から、ファイルを添付するか、ナレッジのタグを選びます。入った資料は「参考資料」に出ます。タグに後から足した文書は、もう一度選ぶまで入りません。
                </p>
                <p>
                  ・「参考資料」は、いま入っている資料の状況です。いらないファイルはここで外せます。ナレッジはチームの中のタグを開くとファイル名が出ます。文書ごとの削除はありません。
                </p>
                <p>・エージェントで使う MCP の On/Off、プロンプト、追加は右上の「MCP」から行います。</p>
                <p>
                  ・入力欄の「Web検索」は、MCP の「Web検索」と同じスイッチです。On
                  にすると、対話の中でウェブを検索します。
                </p>
                <p>
                  ・共有ナレッジの MCP が On のあいだは、共有ナレッジの文書がすべて対象です。一部のタグだけにするには、MCP を Off にしてからそのタグを登録します。
                </p>
                <p>
                  ・「エージェント」で、何を作るかを話します。決まると、資料を調べて項目へ書きます。確認が必要なときだけ、そこで聞きます。
                </p>
                <p>
                  ・項目が揃うと、そのゴールを生成指示として Markdown エディタを開きます。生成指示の入力や、渡し先の選択はありません。
                </p>
              </div>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};
