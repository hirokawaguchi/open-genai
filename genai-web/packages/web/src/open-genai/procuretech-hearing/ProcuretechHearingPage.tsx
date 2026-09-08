import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Textarea } from '@/components/ui/dads/Textarea';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { PROCURETECH_HEARING_EXAPP_ID } from '@/layout/navItems';
import { ApiError } from '@/lib/fetcher';
import {
  downloadHearingTemplate,
  downloadHearingWorkbook,
  fileToBase64,
  useHearingActions,
  useHearingConfig,
  useHearingSession,
  useHearingSessions,
} from './useProcuretechHearing';

const Spinner = () => (
  <span
    className='inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-solid-gray-300 border-t-blue-900'
    role='status'
    aria-label='処理中'
  />
);

const UnavailableNotice = ({ message }: { message?: string }) => (
  <div
    className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
    role='status'
  >
    <p className='text-std-16B-150 text-solid-gray-900'>
      ヒアリングシートに接続できません
    </p>
    <p className='mt-2 text-solid-gray-700'>
      {message || '`docker compose up -d` でサービスを起動してください。'}
    </p>
    <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
      docker compose up -d --build
    </pre>
  </div>
);

export const ProcuretechHearingPage = () => {
  const { config, isLoading: configLoading, unavailable } = useHearingConfig();
  const { sessions, mutate: mutateSessions } = useHearingSessions();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { detail, mutate: mutateDetail } = useHearingSession(sessionId);
  const actions = useHearingActions();
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState('');
  const [instruction, setInstruction] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { label: string; value: string }>>({});
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    if (!detail) return;
    setTitle(detail.title);
    setInstruction(detail.instruction);
    setDrafts(
      Object.fromEntries(detail.items.map((i) => [i.id, { label: i.label, value: i.value }])),
    );
  }, [detail]);

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

  const onDeleteSession = async () => {
    if (!sessionId) return;
    if (!window.confirm('この作業を削除しますか？')) return;
    const ok = await actions.deleteSession(sessionId);
    if (!ok) return;
    setSessionId(null);
    await mutateSessions();
  };

  const onDownloadTemplate = async () => {
    setDownloadError(null);
    try {
      await downloadHearingTemplate();
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
      await downloadHearingWorkbook(sessionId);
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
      <PageTitle title='ヒアリングシート' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-4 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={PROCURETECH_HEARING_EXAPP_ID}
          fallbackTitle='ヒアリングシート'
          fallbackDescription='複数の参考資料から項目と値を整理し、文書生成用の Excel を作ります。'
          fallbackHowTo={
            <>
              <p>・左で作業を選び、参考ファイルを追加します。</p>
              <p>・右で項目（設問）を増やし、値を手入力するか「生成」します。</p>
              <p>・生成は各行だけを対象にし、参考ファイルの本文だけを材料にします。</p>
              <p>・記入済みシートをダウンロードし、Markdown エディタの生成入力として使えます。</p>
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
                  新しい作業
                </Button>
                <Button type='button' variant='outline' size='md' onClick={() => void onDownloadTemplate()}>
                  空の雛形
                </Button>
              </div>

              <section>
                <h2 className='mb-2 text-std-16B-150'>作業一覧</h2>
                {sessions.length === 0 ? (
                  <p className='text-dns-14N-130 text-solid-gray-600'>まだ作業がありません。</p>
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
                          {s.title || '無題'}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {detail && (
                <section className='flex flex-col gap-2'>
                  <h2 className='text-std-16B-150'>参考ファイル</h2>
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
                            <span className='break-all text-solid-gray-900'>{f.filename}</span>
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
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </aside>

            <section className='flex min-w-0 flex-col gap-4'>
              {!detail ? (
                <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4 text-std-16N-170 text-solid-gray-700'>
                  左で作業を選ぶか、「新しい作業」を作成してください。
                </div>
              ) : (
                <>
                  <div className='flex flex-col gap-2'>
                    <Label htmlFor='hearing-title'>作業名</Label>
                    <Input
                      id='hearing-title'
                      blockSize='md'
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      onBlur={() => void onSaveTitle()}
                    />
                  </div>

                  <div className='flex flex-col gap-3'>
                    <div className='flex items-center justify-between gap-2'>
                      <h2 className='text-std-18B-160'>項目</h2>
                      <Button type='button' variant='outline' size='sm' onClick={() => void onAddItem()}>
                        項目を追加
                      </Button>
                    </div>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      項目名が設問です。生成はその行の項目名と参考ファイルだけを使います。
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
                            <Label htmlFor={`hearing-label-${item.id}`}>項目 {index + 1}</Label>
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
                            id={`hearing-label-${item.id}`}
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
                          <Textarea
                            id={`hearing-value-${item.id}`}
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
                        </article>
                      );
                    })}
                  </div>

                  <div className='flex flex-col gap-2'>
                    <Label htmlFor='hearing-instruction'>生成指示</Label>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      Markdown エディタ／generate-app へ渡す処理の指示です。
                    </p>
                    <Textarea
                      id='hearing-instruction'
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
                      この作業を削除
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
