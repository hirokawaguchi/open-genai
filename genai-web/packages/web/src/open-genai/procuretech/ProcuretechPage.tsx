import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { PiDownloadSimpleBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { PROCURETECH_EXAPP_ID } from '@/layout/navItems';
import { ApiError } from '@/lib/fetcher';
import type { ProcuretechSection, ProcuretechSessionDetail } from './types';
import {
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

const UPLOAD_TAB = 'upload';
const EXPORT_TAB = 'export';

const UnavailableNotice = ({ message }: { message?: string }) => (
  <div
    className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
    role='status'
  >
    <p className='text-std-16B-150 text-solid-gray-900'>
      情報化企画書ナビは現在有効化されていません
    </p>
    <p className='mt-2 text-solid-gray-700'>
      {message || 'コンテナを profiles: ["procuretech"] で起動してください。'}
    </p>
    <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
      docker compose --profile procuretech up -d{'\n'}# または .env に COMPOSE_PROFILES=procuretech
    </pre>
  </div>
);

const SectionChat = ({
  section,
  priorSections,
  sessionId,
  onChanged,
}: {
  section: ProcuretechSection;
  priorSections: ProcuretechSection[];
  sessionId: string;
  onChanged: () => void | Promise<void>;
}) => {
  const { finalize, clearSection, submitting, error, setError } = useProcuretechActions();
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  const busy = sending || submitting;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [streamingText, pendingUser, section.messages.length]);

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

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter で送信 / Shift+Enter で改行。日本語入力の変換確定 Enter は送信しない。
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
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

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-col gap-1'>
        <h3 className='text-std-18B-160'>
          項番{section.item_no}: {section.title}
        </h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>{section.description}</p>
      </div>

      <div className='max-h-[420px] overflow-auto rounded-8 border border-solid-gray-300 p-3'>
        <ul className='flex flex-col gap-3'>
          {priorSections
            .filter((p) => p.cell_value)
            .map((p) => (
              <li key={`prior-${p.key}`} className='flex justify-start'>
                <div className='max-w-[90%] rounded-8 border border-blue-200 bg-blue-50 px-3 py-2'>
                  <p className='mb-1 text-dns-14N-130 text-blue-900'>
                    項番{p.item_no}「{p.title}」の最新の内容（この項番の対話に反映されます）
                  </p>
                  <div className='whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'>
                    {p.cell_value}
                  </div>
                </div>
              </li>
            ))}
          {section.cell_value && (
            <li className='flex justify-start'>
              <div className='max-w-[90%] rounded-8 border border-solid-gray-300 bg-white px-3 py-2'>
                <p className='mb-1 text-dns-14N-130 text-solid-gray-600'>
                  現在の記載{section.finalized ? '・このセッションで書き出し済み' : ''}
                </p>
                <div className='whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'>
                  {section.cell_value}
                </div>
              </div>
            </li>
          )}
          {section.messages.length === 0 && !sending && pendingUser === null && (
            <li className='text-dns-14N-130 text-solid-gray-600'>
              「こんにちは」から対話を始めましょう。困ったら「わかりません」と入力しても構いません。
            </li>
          )}
          {section.messages.map((m, i) => (
            <li
              key={`${section.key}-${i}`}
              className={m.role === 'assistant' ? 'flex justify-start' : 'flex justify-end'}
            >
              <div
                className={
                  m.role === 'assistant'
                    ? 'max-w-[90%] whitespace-pre-wrap rounded-8 bg-solid-gray-50 px-3 py-2 text-std-16N-170 text-solid-gray-900'
                    : 'max-w-[90%] whitespace-pre-wrap rounded-8 bg-blue-50 px-3 py-2 text-std-16N-170 text-solid-gray-900'
                }
              >
                {m.content}
              </div>
            </li>
          ))}
          {pendingUser !== null && (
            <li className='flex justify-end'>
              <div className='max-w-[90%] whitespace-pre-wrap rounded-8 bg-blue-50 px-3 py-2 text-std-16N-170 text-solid-gray-900'>
                {pendingUser}
              </div>
            </li>
          )}
          {sending && (
            <li className='flex justify-start'>
              <div className='flex max-w-[90%] items-center gap-2 rounded-8 bg-solid-gray-50 px-3 py-2 text-std-16N-170 text-solid-gray-900'>
                {streamingText ? (
                  <span className='whitespace-pre-wrap'>{streamingText}</span>
                ) : null}
                <Spinner />
              </div>
            </li>
          )}
          <div ref={bottomRef} />
        </ul>
      </div>

      {error && (
        <p className='text-dns-16N-130 text-error-1' role='alert'>
          {error}
        </p>
      )}

      <form onSubmit={onSubmit} className='flex flex-col gap-2'>
        <Label htmlFor={`pt-input-${section.key}`} size='sm'>
          メッセージ（Enter で送信 / Shift+Enter で改行）
        </Label>
        <textarea
          id={`pt-input-${section.key}`}
          className='w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={section.chat_placeholder}
        />
        <div className='flex flex-wrap items-center gap-2'>
          <Button
            type='submit'
            variant='solid-fill'
            size='md'
            aria-disabled={busy || !input.trim()}
          >
            {sending ? '応答中...' : '送信'}
          </Button>
          <Button
            type='button'
            variant='outline'
            size='md'
            aria-disabled={busy || section.messages.length === 0}
            onClick={onFinalize}
          >
            {submitting ? '書き戻し中...' : 'この項番の内容を整理して情報化企画書に書き戻す'}
          </Button>
          {section.messages.length > 0 && (
            <Button
              type='button'
              variant='text'
              size='md'
              aria-disabled={busy}
              onClick={onClear}
            >
              この分野の履歴をクリア
            </Button>
          )}
        </div>
      </form>
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
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h3 className='text-std-18B-160'>書き出しとダウンロード</h3>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          aria-disabled={!anyFinalized || undefined}
          onClick={onDownload}
        >
          <span className='inline-flex items-center gap-1 whitespace-nowrap'>
            <PiDownloadSimpleBold className='size-4 shrink-0' />
            更新版をダウンロード
          </span>
        </Button>
      </div>
      {!anyFinalized && (
        <p className='text-dns-14N-130 text-solid-gray-600'>
          各項番のタブで「この項番の内容を整理して情報化企画書に書き戻す」を押すと、ここに書き出し内容が表示され、更新版をダウンロードできます。
        </p>
      )}
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
  const { config, isLoading: configLoading, unavailable } = useProcuretechConfig();
  const { sessions, mutate: mutateSessions } = useProcuretechSessions();
  const { createSession, deleteSession, submitting, error, setError } = useProcuretechActions();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>(UPLOAD_TAB);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { detail, mutate: mutateDetail } = useProcuretechSession(sessionId);

  const metaSections = detail?.sections ?? config?.sections ?? [];
  const finalizedKeys = useMemo(
    () => new Set((detail?.sections ?? []).filter((s) => s.finalized).map((s) => s.key)),
    [detail],
  );

  const currentSection = useMemo(
    () => detail?.sections.find((s) => s.key === activeTab) ?? null,
    [detail, activeTab],
  );

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
      setSessionId(created.id);
      setActiveTab(created.sections[0]?.key ?? UPLOAD_TAB);
      await mutateSessions();
    }
    if (fileRef.current) fileRef.current.value = '';
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

  const onDeleteSession = async () => {
    if (!sessionId) return;
    if (!window.confirm('このセッション（会話履歴と読み込んだ企画書）を削除しますか？')) return;
    const ok = await deleteSession(sessionId);
    if (ok) {
      setSessionId(null);
      setActiveTab(UPLOAD_TAB);
      await mutateSessions();
    }
  };

  const onChanged = async () => {
    await mutateDetail();
    void mutateSessions();
  };

  const tabBtn = (key: string, label: string) => (
    <button
      key={key}
      type='button'
      onClick={() => setActiveTab(key)}
      className={
        key === activeTab
          ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
          : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900'
      }
    >
      {label}
    </button>
  );

  const needSession = (
    <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4 text-std-16N-170 text-solid-gray-700'>
      先に「読み込み」タブで情報化企画書（.xlsx）を読み込んでください。
    </div>
  );

  return (
    <LayoutBody>
      <PageTitle title='情報化企画書ナビ' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-4 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={PROCURETECH_EXAPP_ID}
          fallbackTitle='情報化企画書ナビ'
          fallbackDescription='情報化企画書（Excel）を読み込み、4分野をAIとの対話で整理して各欄へ書き出します。'
          fallbackHowTo={
            <>
              <p>・「読み込み」タブで情報化企画書（.xlsx）を読み込みます。</p>
              <p>・項番1〜4のタブを切り替え、AIと対話して内容を整理します（Enterで送信）。</p>
              <p>・「この項番の内容を整理して情報化企画書に書き戻す」で該当欄へ書き出します。</p>
              <p>・「書き出し」タブから更新版をダウンロードできます。</p>
              {config?.llm?.model && <p>・利用モデル: {config.llm.model}</p>}
            </>
          }
        />

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <UnavailableNotice message={config?.error} />
        )}

        {!unavailable && (
          <>
            <div className='flex flex-wrap gap-1 overflow-x-auto border-b border-solid-gray-300'>
              {tabBtn(UPLOAD_TAB, '読み込み')}
              {metaSections.map((s) =>
                tabBtn(
                  s.key,
                  `項番${s.item_no}: ${s.title}${finalizedKeys.has(s.key) ? ' ✓' : ''}`,
                ),
              )}
              {tabBtn(EXPORT_TAB, '書き出し・ダウンロード')}
            </div>

            {activeTab === UPLOAD_TAB && (
              <section className='flex flex-col gap-4'>
                <div className='flex flex-col gap-2'>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    情報化企画書の様式（.xlsx）を読み込みます。
                  </p>
                  <input
                    ref={fileRef}
                    type='file'
                    accept='.xlsx'
                    className='sr-only'
                    onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
                  />
                  <div className='flex flex-wrap items-center gap-3'>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      aria-disabled={submitting || undefined}
                      onClick={() => fileRef.current?.click()}
                    >
                      ファイルを選択
                    </Button>
                    <p className='text-std-14N-170 text-solid-gray-700'>
                      {submitting && !detail ? '読み込み中...' : '.xlsx ファイルを選択してください'}
                    </p>
                  </div>
                  {error && (
                    <p className='text-dns-16N-130 text-error-1' role='alert'>
                      {error}
                    </p>
                  )}
                </div>

                {sessions.length > 0 && (
                  <div className='flex flex-col gap-2'>
                    <h2 className='text-std-16B-150'>読み込み済みの企画書</h2>
                    <ul className='flex flex-col gap-1'>
                      {sessions.map((s) => (
                        <li key={s.id} className='flex flex-wrap items-center gap-2'>
                          <button
                            type='button'
                            onClick={() => {
                              setSessionId(s.id);
                              setActiveTab(UPLOAD_TAB);
                            }}
                            className={
                              s.id === sessionId
                                ? 'text-std-16B-150 text-blue-900 underline underline-offset-2'
                                : 'text-std-16N-170 text-blue-900 underline-offset-2 hover:underline'
                            }
                          >
                            {s.filename}
                          </button>
                          <span className='text-dns-14N-130 text-solid-gray-600'>
                            {new Date(s.updated_at).toLocaleString('ja-JP')}
                          </span>
                          {s.id === sessionId && (
                            <Button
                              type='button'
                              variant='text'
                              size='sm'
                              onClick={onDeleteSession}
                            >
                              削除
                            </Button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {detail && (
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    現在のセッション: {detail.filename}。上部のタブから各分野の対話に進めます。
                  </p>
                )}
              </section>
            )}

            {activeTab !== UPLOAD_TAB &&
              activeTab !== EXPORT_TAB &&
              (currentSection && detail ? (
                <SectionChat
                  key={currentSection.key}
                  section={currentSection}
                  priorSections={detail.sections.filter(
                    (s) => s.item_no < currentSection.item_no,
                  )}
                  sessionId={detail.id}
                  onChanged={onChanged}
                />
              ) : (
                needSession
              ))}

            {activeTab === EXPORT_TAB &&
              (detail ? (
                <ExportPanel
                  detail={detail}
                  onDownload={onDownload}
                  downloadError={downloadError}
                />
              ) : (
                needSession
              ))}
          </>
        )}
      </div>
    </LayoutBody>
  );
};
