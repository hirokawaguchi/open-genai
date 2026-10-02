import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { PiBookOpenBold, PiDownloadSimple, PiDownloadSimpleBold, PiFilePlus } from 'react-icons/pi';
import { PageTitle } from '@/components/PageTitle';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useSubmitKey } from '@/hooks/useSubmitKey';
import { LayoutBody } from '@/layout/LayoutBody';
import { PROCURETECH_EXAPP_ID } from '@/layout/navItems';
import { ApiError } from '@/lib/fetcher';
import { requestSubmitOnEnter } from '@/utils/keyboard';
import type { ProcuretechSection, ProcuretechSessionDetail } from './types';
import {
  downloadProcuretechTemplate,
  downloadProcuretechWorkbook,
  fileToBase64,
  streamProcuretechChat,
  useProcuretechActions,
  useProcuretechConfig,
  useProcuretechSession,
  useProcuretechSessions,
} from './useProcuretech';

const Spinner = () => (
  <span
    className='inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-solid-gray-300 border-t-blue-900'
    role='status'
    aria-label='応答生成中'
  />
);

const LIST_TAB = 'list';
const CHAT_TAB = 'chat';
const EXPORT_TAB = 'export';

const PANE_TABS = [
  { id: LIST_TAB, label: '企画書一覧' },
  { id: CHAT_TAB, label: '対話' },
  { id: EXPORT_TAB, label: '書き出し' },
] as const;

type PaneId = (typeof PANE_TABS)[number]['id'];

const FALLBACK_DESCRIPTION =
  '情報化企画書（Excel）を読み込み、4分野をAIとの対話で整理して各欄へ書き出します。';

const FALLBACK_TEMPLATES = [
  { key: 'systemplan', label: '情報化企画書（systemplan.xlsx）', filename: 'systemplan.xlsx' },
  { key: 'global', label: '全般的事項（global.xlsx）', filename: 'global.xlsx' },
];

const FALLBACK_HOW_TO = [
  '「企画書一覧」で情報化企画書（.xlsx）を読み込みます。様式（記入サンプル付き）は同じ画面からダウンロードできます。',
  '「対話」で項番を切り替え、AIと対話して内容を整理します。',
  '「この項番を企画書に書き戻す」で該当欄へ書き出します。',
  '「書き出し」から更新版をダウンロードできます。',
];

const UnavailableNotice = ({ message }: { message?: string }) => (
  <div
    className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
    role='status'
  >
    <p className='text-std-16B-150 text-solid-gray-900'>
      情報化企画書ナビは現在有効化されていません
    </p>
    <p className='mt-2 text-solid-gray-700'>
      {message || 'コンテナを profiles: ["procuretech-navigator"] で起動してください。'}
    </p>
    <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
      docker compose --profile procuretech-navigator up -d{'\n'}# または .env に COMPOSE_PROFILES=procuretech-navigator
    </pre>
  </div>
);

const SectionChat = ({
  section,
  sections,
  priorSections,
  filename,
  sessionId,
  onSectionChange,
  onChanged,
}: {
  section: ProcuretechSection;
  sections: ProcuretechSection[];
  priorSections: ProcuretechSection[];
  filename: string;
  sessionId: string;
  onSectionChange: (key: string) => void;
  onChanged: () => void | Promise<void>;
}) => {
  const { hint } = useSubmitKey();
  const { finalize, clearSection, submitting, error, setError } = useProcuretechActions();
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLDivElement>(null);
  const [formH, setFormH] = useState(0);

  const busy = sending || submitting;

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
    const el = bottomRef.current;
    if (!el) return;
    const id = window.requestAnimationFrame(() => {
      el.scrollIntoView({ block: 'end', behavior: 'instant' });
    });
    return () => window.cancelAnimationFrame(id);
  }, [streamingText, pendingUser, section.messages.length, formH]);

  const submit = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setError(null);
    setInput('');
    setPendingUser(text);
    setStreamingText('');
    setSending(true);
    try {
      const res = await streamProcuretechChat(sessionId, section.key, text, {
        onDelta: (t) => setStreamingText((prev) => prev + t),
      });
      if (res) await onChanged();
    } catch (e) {
      setInput(text);
      const msg =
        e instanceof ApiError
          ? ((e.data as { error?: string } | undefined)?.error ?? 'メッセージの送信に失敗しました。')
          : 'メッセージの送信に失敗しました。';
      setError(msg);
    } finally {
      setSending(false);
      setPendingUser(null);
      setStreamingText('');
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit();
  };

  const onFinalize = async () => {
    if (busy || section.messages.length === 0) return;
    setError(null);
    const res = await finalize(sessionId, section.key);
    if (res) await onChanged();
  };

  const onClear = async () => {
    if (busy) return;
    setError(null);
    const res = await clearSection(sessionId, section.key);
    if (res) await onChanged();
  };

  const empty = section.messages.length === 0 && !sending && pendingUser === null;

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-2'>
      <div className='flex shrink-0 flex-wrap items-center gap-2 rounded-8 border border-solid-gray-300 px-3 py-2'>
        <label
          htmlFor={`pt-section-${section.key}`}
          className='text-dns-14N-130 text-solid-gray-700'
        >
          項番
        </label>
        <Select
          id={`pt-section-${section.key}`}
          blockSize='sm'
          value={section.key}
          aria-disabled={busy || undefined}
          onChange={(e) => onSectionChange(e.target.value)}
          className='max-w-80'
        >
          {sections.map((s) => (
            <option key={s.key} value={s.key}>
              {`項番${s.item_no}: ${s.title}${s.finalized ? ' ✓' : ''}`}
            </option>
          ))}
        </Select>
        <span className='max-w-64 truncate text-std-14N-160 text-solid-gray-800' title={filename}>
          {filename}
        </span>
        {section.finalized && (
          <span className='rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
            書き出し済み
          </span>
        )}
        <span className='ml-auto flex flex-wrap gap-2'>
          <Button
            type='button'
            variant='outline'
            size='sm'
            aria-disabled={busy || section.messages.length === 0 || undefined}
            onClick={() => void onFinalize()}
          >
            {submitting ? '書き戻し中...' : 'この項番を企画書に書き戻す'}
          </Button>
          {section.messages.length > 0 && (
            <Button
              type='button'
              variant='text'
              size='sm'
              aria-disabled={busy || undefined}
              onClick={() => void onClear()}
            >
              履歴をクリア
            </Button>
          )}
        </span>
      </div>
      {section.description && (
        <p className='shrink-0 text-dns-14N-130 text-solid-gray-600'>{section.description}</p>
      )}

      <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto py-1'>
        {priorSections
          .filter((p) => p.cell_value)
          .map((p) => (
            <div key={`prior-${p.key}`} className='flex justify-start'>
              <div className='max-w-[90%] rounded-8 border border-blue-200 bg-blue-50 px-3 py-2'>
                <p className='mb-1 text-dns-14N-130 text-blue-900'>
                  項番{p.item_no}「{p.title}」の最新の内容（この項番の対話に反映されます）
                </p>
                <div className='whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'>
                  {p.cell_value}
                </div>
              </div>
            </div>
          ))}
        {section.cell_value && (
          <div className='flex justify-start'>
            <div className='max-w-[90%] rounded-8 border border-solid-gray-300 bg-white px-3 py-2'>
              <p className='mb-1 text-dns-14N-130 text-solid-gray-600'>
                現在の記載{section.finalized ? '・このセッションで書き出し済み' : ''}
              </p>
              <div className='whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'>
                {section.cell_value}
              </div>
            </div>
          </div>
        )}
        {empty && (
          <p className='text-std-16N-170 text-solid-gray-536'>
            「こんにちは」から対話を始めましょう。困ったら「わかりません」と入力しても構いません。
          </p>
        )}
        {section.messages.map((m, i) => (
          <div
            key={`${section.key}-${i}`}
            className={m.role === 'assistant' ? 'flex justify-start' : 'flex justify-end'}
          >
            <div
              className={
                m.role === 'assistant'
                  ? 'max-w-[85%] whitespace-pre-wrap rounded-8 border border-solid-gray-420 bg-white px-4 py-3 text-std-16N-170 text-solid-gray-900'
                  : 'max-w-[85%] whitespace-pre-wrap rounded-8 bg-blue-50 px-4 py-3 text-std-16N-170 text-solid-gray-800'
              }
            >
              {m.content}
            </div>
          </div>
        ))}
        {pendingUser !== null && (
          <div className='flex justify-end'>
            <div className='max-w-[85%] whitespace-pre-wrap rounded-8 bg-blue-50 px-4 py-3 text-std-16N-170 text-solid-gray-800'>
              {pendingUser}
            </div>
          </div>
        )}
        {sending && (
          <div className='flex justify-start'>
            <div className='flex max-w-[85%] items-center gap-2 rounded-8 border border-solid-gray-420 bg-white px-4 py-3 text-std-16N-170 text-solid-gray-900'>
              {streamingText ? <span className='whitespace-pre-wrap'>{streamingText}</span> : null}
              <Spinner />
            </div>
          </div>
        )}
        <div ref={bottomRef} className='h-px' style={{ scrollMarginBottom: formH }} />
      </div>

      {error && (
        <p className='shrink-0 text-dns-16N-130 text-error-1' role='alert'>
          {error}
        </p>
      )}

      <div
        ref={formRef}
        className='sticky bottom-0 z-1 shrink-0 border-t border-t-solid-gray-800 bg-white pb-2'
      >
        <form
          className='w-full'
          onSubmit={onSubmit}
          aria-labelledby={`pt-input-heading-${section.key}`}
        >
          <h2 id={`pt-input-heading-${section.key}`} className='my-1 text-std-16N-170'>
            {empty
              ? '調べたいことやお困りごとなど、何でも入力してみましょう'
              : '追加で質問や不明点などあれば返答してみましょう'}
          </h2>
          <SupportText id={`pt-input-${section.key}-submit-hint`} className='mb-1'>
            {hint}
          </SupportText>
          <div className='flex flex-col gap-2'>
            <AutoResizeTextarea
              id={`pt-input-${section.key}`}
              className='resize-none'
              rows={empty ? 3 : 1}
              value={input}
              placeholder={section.chat_placeholder}
              aria-labelledby={`pt-input-heading-${section.key}`}
              aria-describedby={`pt-input-${section.key}-submit-hint`}
              onKeyDown={requestSubmitOnEnter}
              onChange={(e) => setInput(e.target.value)}
            />
            <div className='flex justify-end'>
              <LoadingButton
                type='submit'
                variant='solid-fill'
                size='md'
                disabled={busy || !input.trim()}
                loading={sending}
                className='inline-flex min-w-36 items-center justify-center gap-1'
              >
                <SendIcon aria-hidden={true} className='shrink-0' />
                {sending ? '応答中...' : '送信'}
              </LoadingButton>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

const ExportPanel = ({
  detail,
  onDownload,
  downloadError,
}: {
  detail: ProcuretechSessionDetail;
  onDownload: () => void;
  downloadError: string | null;
}) => {
  const anyFinalized = detail.sections.some((s) => s.finalized);
  return (
    <div className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <h2 className='text-std-18B-160 text-solid-gray-900'>書き出し</h2>
        <Button
          type='button'
          variant='solid-fill'
          size='sm'
          aria-disabled={!anyFinalized || undefined}
          onClick={onDownload}
        >
          <span className='inline-flex items-center gap-1 whitespace-nowrap'>
            <PiDownloadSimpleBold className='size-4 shrink-0' />
            更新版をダウンロード
          </span>
        </Button>
      </div>
      <p className='text-dns-14N-130 text-solid-gray-600'>
        {detail.filename}
        {anyFinalized
          ? '。書き戻した欄が更新版に入ります。'
          : '。対話タブで項番を書き戻すと、ここに内容が表示され、更新版をダウンロードできます。'}
      </p>
      {downloadError && (
        <p className='text-dns-16N-130 text-error-1' role='alert'>
          {downloadError}
        </p>
      )}
      <ul className='flex flex-col gap-3'>
        {detail.sections.map((s) => (
          <li key={s.key} className='rounded-8 border border-solid-gray-300 p-3'>
            <div className='flex items-center justify-between gap-2'>
              <p className='text-std-16B-150 text-solid-gray-900'>
                項番{s.item_no}: {s.title}
              </p>
              <span
                className={
                  s.finalized
                    ? 'text-dns-14N-130 text-blue-900'
                    : 'text-dns-14N-130 text-solid-gray-500'
                }
              >
                {s.finalized ? '書き出し済み' : '未書き出し'}
              </span>
            </div>
            <pre className='mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-std-14N-160 text-solid-gray-800'>
              {s.cell_value || '（未記入）'}
            </pre>
          </li>
        ))}
      </ul>
    </div>
  );
};

export const ProcuretechPage = () => {
  const { documentTitle, howToUse, title, description } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    PROCURETECH_EXAPP_ID,
    '情報化企画書ナビ',
    FALLBACK_DESCRIPTION,
  );
  const { config, isLoading: configLoading, unavailable } = useProcuretechConfig();
  const { sessions, mutate: mutateSessions } = useProcuretechSessions();
  const { createSession, deleteSession, submitting, error, setError } = useProcuretechActions();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pane, setPane] = useState<PaneId>(LIST_TAB);
  const [sectionKey, setSectionKey] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const {
    detail,
    isLoading: sessionLoading,
    loadError,
    mutate: mutateDetail,
  } = useProcuretechSession(sessionId);

  const finalizedCount = useMemo(
    () => (detail?.sections ?? []).filter((s) => s.finalized).length,
    [detail],
  );

  const currentSection = useMemo(() => {
    if (!detail) return null;
    return detail.sections.find((s) => s.key === sectionKey) ?? detail.sections[0] ?? null;
  }, [detail, sectionKey]);

  const openSession = (id: string, firstKey?: string | null) => {
    setSessionId(id);
    if (firstKey) setSectionKey(firstKey);
    setPane(CHAT_TAB);
  };

  const onPickFile = async (file: File | null) => {
    if (!file) return;
    setError(null);
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      setError('情報化企画書は .xlsx 形式でアップロードしてください。');
      return;
    }
    const dataUrl = await fileToBase64(file);
    const created = await createSession(file.name, dataUrl);
    if (created) {
      openSession(created.id, created.sections[0]?.key ?? null);
      await mutateSessions();
    }
    if (fileRef.current) fileRef.current.value = '';
  };

  const onDownloadTemplate = async (key: string, filename: string) => {
    setDownloadError(null);
    try {
      await downloadProcuretechTemplate(key, filename);
    } catch (e) {
      setDownloadError(
        e instanceof ApiError
          ? ((e.data as { error?: string } | undefined)?.error ?? '様式のダウンロードに失敗しました。')
          : '様式のダウンロードに失敗しました。',
      );
    }
  };

  const onDownload = async () => {
    if (!sessionId) return;
    setDownloadError(null);
    try {
      await downloadProcuretechWorkbook(sessionId);
    } catch {
      setDownloadError('ダウンロードに失敗しました。時間をおいて再度お試しください。');
    }
  };

  const onDeleteSession = async (id: string, filename: string) => {
    if (!window.confirm(`「${filename}」のセッション（会話履歴と読み込んだ企画書）を削除しますか？`))
      return;
    const ok = await deleteSession(id);
    if (ok) {
      if (id === sessionId) {
        setSessionId(null);
        setSectionKey(null);
        setPane(LIST_TAB);
      }
      await mutateSessions();
    }
  };

  const onChanged = async () => {
    await mutateDetail();
    void mutateSessions();
  };

  const templates = config?.templates?.length ? config.templates : FALLBACK_TEMPLATES;
  const needSession = pane !== LIST_TAB && !sessionId;
  const sessionPending = pane !== LIST_TAB && Boolean(sessionId) && !detail;
  const workPane = pane === CHAT_TAB;

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div
        className={
          workPane
            ? 'mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) flex-col gap-2 overflow-hidden px-4 py-2 lg:px-6'
            : 'mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'
        }
      >
        {workPane ? (
          <div className='flex min-w-0 items-baseline gap-3'>
            <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{title}</h1>
            {description && (
              <p className='truncate text-dns-14N-130 text-solid-gray-600' title={description}>
                {description}
              </p>
            )}
          </div>
        ) : (
          <ManagedAppHeader
            teamId={COMMON_EXAPPS_TEAM_ID}
            exAppId={PROCURETECH_EXAPP_ID}
            fallbackTitle='情報化企画書ナビ'
            fallbackDescription={FALLBACK_DESCRIPTION}
            hideHowTo={true}
          />
        )}

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
                    {t.id === EXPORT_TAB && detail
                      ? `${t.label}（${finalizedCount}/${detail.sections.length}）`
                      : t.label}
                  </button>
                ))}
              </div>
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

            {error && pane === LIST_TAB && (
              <p className='text-dns-16N-130 text-error-1' role='alert'>
                {error}
              </p>
            )}

            {pane === LIST_TAB && (
              <section className='flex flex-col gap-3'>
                <div className='flex flex-wrap items-end justify-between gap-2'>
                  <h2 className='text-std-18B-160 text-solid-gray-900'>企画書一覧</h2>
                  <div className='flex flex-wrap items-center gap-2'>
                    <input
                      ref={fileRef}
                      type='file'
                      accept='.xlsx'
                      className='sr-only'
                      onChange={(e) => void onPickFile(e.target.files?.[0] ?? null)}
                    />
                    <Button
                      type='button'
                      variant='solid-fill'
                      size='sm'
                      aria-disabled={submitting || undefined}
                      onClick={() => fileRef.current?.click()}
                    >
                      <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                        <PiFilePlus className='size-4' aria-hidden={true} />
                        {submitting && !detail ? '読み込み中...' : '企画書を読み込む'}
                      </span>
                    </Button>
                    {templates.map((tmpl) => (
                      <Button
                        key={tmpl.key}
                        type='button'
                        variant='outline'
                        size='sm'
                        title={tmpl.label}
                        onClick={() => void onDownloadTemplate(tmpl.key, tmpl.filename)}
                      >
                        <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                          <PiDownloadSimple className='size-4' aria-hidden={true} />
                          {tmpl.filename}
                        </span>
                      </Button>
                    ))}
                  </div>
                </div>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  情報化企画書の様式（.xlsx）を読み込みます。記入サンプル付きの様式は右上からダウンロードできます。
                </p>
                {downloadError && (
                  <p className='text-dns-16N-130 text-error-1' role='alert'>
                    {downloadError}
                  </p>
                )}
                <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
                  <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
                    <thead>
                      <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                        <th className='w-3/5 min-w-[20rem] px-3 py-2'>ファイル名</th>
                        <th className='px-3 py-2'>更新日時</th>
                        <th className='px-3 py-2 text-right'>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.length === 0 ? (
                        <tr>
                          <td colSpan={3} className='px-3 py-6 text-center text-solid-gray-500'>
                            企画書がありません。右上から読み込んでください。
                          </td>
                        </tr>
                      ) : (
                        sessions.map((s) => (
                          <tr key={s.id} className='border-b border-solid-gray-200 last:border-b-0'>
                            <td className='w-3/5 min-w-[20rem] px-3 py-2'>
                              <div className='flex items-center gap-2'>
                                <span className='min-w-0 truncate text-std-16N-170 text-solid-gray-900'>
                                  {s.filename}
                                </span>
                                {s.id === sessionId && (
                                  <span className='shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                                    選択中
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className='px-3 py-2 text-solid-gray-600'>
                              {new Date(s.updated_at).toLocaleString('ja-JP')}
                            </td>
                            <td className='px-3 py-2 text-right'>
                              <span className='inline-flex gap-2'>
                                <Button
                                  type='button'
                                  variant='solid-fill'
                                  size='xs'
                                  onClick={() => openSession(s.id)}
                                >
                                  開く
                                </Button>
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='xs'
                                  aria-disabled={submitting || undefined}
                                  onClick={() => void onDeleteSession(s.id, s.filename)}
                                >
                                  削除
                                </Button>
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {needSession && (
              <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
                「企画書一覧」タブから情報化企画書を開いてください。
              </div>
            )}

            {sessionPending && (
              <div
                className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'
                role='status'
              >
                {sessionLoading ? '読み込み中…' : loadError || '企画書を開けませんでした。'}
              </div>
            )}

            {pane === CHAT_TAB && currentSection && detail && (
              <SectionChat
                key={currentSection.key}
                section={currentSection}
                sections={detail.sections}
                priorSections={detail.sections.filter((s) => s.item_no < currentSection.item_no)}
                filename={detail.filename}
                sessionId={detail.id}
                onSectionChange={setSectionKey}
                onChanged={onChanged}
              />
            )}

            {pane === EXPORT_TAB && detail && (
              <ExportPanel
                detail={detail}
                onDownload={() => void onDownload()}
                downloadError={downloadError}
              />
            )}
          </>
        )}
      </div>

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
                {FALLBACK_HOW_TO.map((line) => (
                  <p key={line}>・{line}</p>
                ))}
              </div>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};
