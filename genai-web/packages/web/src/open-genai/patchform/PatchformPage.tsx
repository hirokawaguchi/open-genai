import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { PiBookOpenBold, PiNotePencilBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import {
  usePatchformActions,
  usePatchformAssist,
  usePatchformConfig,
  usePatchformList,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
  closed: '受付終了',
  archived: 'アーカイブ',
};

/**
 * フォーム専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["patchform"] 未起動時は有効化手順を案内する。
 */
export const PatchformPage = () => {
  const navigate = useNavigate();
  const { config, isLoading: configLoading, unavailable } = usePatchformConfig();
  const { forms, isLoading, loadError, mutate } = usePatchformList();
  const { create, submitting, error, setError } = usePatchformActions();
  const {
    generate,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [aiText, setAiText] = useState('');
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError('タイトルを入力してください。');
      return;
    }
    const detail = await create({
      title: title.trim(),
      description: description.trim() || undefined,
      visibility: 'internal',
    });
    if (detail) {
      await mutate();
      navigate(`/patchform/${detail.id}/edit`);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={PATCHFORM_LABEL} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <div className='flex flex-col gap-4'>
          <BreadcrumbsNav
            items={[
              { label: 'ホーム', to: '/' },
              { label: 'AIアプリ', to: '/apps' },
              { label: PATCHFORM_LABEL },
            ]}
          />
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>{PATCHFORM_LABEL}</h1>
          <p className='text-std-16N-170 text-solid-gray-700'>
            庁内利用者と外部回答者向けのオンラインフォームです。外部には別
            URL（公開エンドポイント）で回答してもらえます。
          </p>
          <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
            <DisclosureSummary>
              <span className='flex items-center text-std-16B-150'>
                <PiBookOpenBold className='mr-2 size-5 flex-none' />
                使い方（クリックで開閉）
              </span>
            </DisclosureSummary>
            <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
              <p>・フォームを作成し、部品を並べてから公開します。</p>
              <p>・外部 URL は LGWAN から届かない場合、リンクファイルを持ち出して別端末で開いてください。</p>
              <p>
                ・有効化: <code>docker compose --profile patchform up -d</code> または{' '}
                <code>COMPOSE_PROFILES=patchform</code>
              </p>
              {config?.retention_days != null && (
                <p>・既定の保持期間は {config.retention_days} 日です（フォームごとに変更できます）。</p>
              )}
            </div>
          </Disclosure>
        </div>

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              {PATCHFORM_LABEL}は現在有効化されていません
            </p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error || 'コンテナを profiles: ["patchform"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile patchform up -d{'\n'}
              # または .env に COMPOSE_PROFILES=patchform
            </pre>
          </div>
        )}

        {!unavailable && (
          <>
            <section className='flex flex-col gap-4'>
              <h2 className='flex items-center gap-2 text-std-18B-160'>
                <PiNotePencilBold className='size-5' />
                新しいフォーム
              </h2>
              <form onSubmit={onSubmit} className='flex flex-col gap-4'>
                <div>
                  <Label htmlFor='pf-title' size='sm'>
                    タイトル
                  </Label>
                  <input
                    id='pf-title'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <Label htmlFor='pf-desc' size='sm'>
                    説明（任意）
                  </Label>
                  <textarea
                    id='pf-desc'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                  <Label htmlFor='pf-ai' size='sm'>
                    AIで下書きを作る
                  </Label>
                  <textarea
                    id='pf-ai'
                    className='w-full rounded-4 border border-solid-gray-420 bg-white px-3 py-2 text-std-16N-170'
                    rows={2}
                    value={aiText}
                    onChange={(e) => setAiText(e.target.value)}
                    placeholder='例: 子ども医療費助成の申請。申請者・住所・振込先が必要'
                  />
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    モデル: {config?.llm?.model || '（未設定）'}。失敗時はテンプレートにフォールバックします。
                  </p>
                  {(assistError || aiNotes) && (
                    <p
                      className={
                        assistError ? 'text-dns-14N-130 text-error-1' : 'text-dns-14N-130 text-solid-gray-700'
                      }
                      role={assistError ? 'alert' : undefined}
                    >
                      {assistError || aiNotes}
                    </p>
                  )}
                  <div>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      aria-disabled={assistBusy || submitting || !aiText.trim()}
                      onClick={async () => {
                        setAssistError(null);
                        setAiNotes(null);
                        const res = await generate({ text: aiText.trim() });
                        if (!res) return;
                        const created = await create({
                          title: res.definition.metadata.title || title.trim() || 'AI下書き',
                          description: res.definition.metadata.description || description.trim() || undefined,
                          definition: res.definition,
                          visibility: 'internal',
                        });
                        if (created) {
                          await mutate();
                          navigate(`/patchform/${created.id}/edit`);
                        } else {
                          setAiNotes(res.notes || '下書きを生成しましたが、作成に失敗しました。');
                        }
                      }}
                    >
                      {assistBusy || submitting ? '生成中...' : '生成して編集する'}
                    </Button>
                  </div>
                </div>
                {error && (
                  <p className='text-dns-16N-130 text-error-1' role='alert'>
                    {error}
                  </p>
                )}
                <div>
                  <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
                    {submitting ? '作成中...' : '作成して編集する'}
                  </Button>
                </div>
              </form>
            </section>

            <section className='flex flex-col gap-3'>
              <h2 className='text-std-18B-160'>自分のフォーム</h2>
              <div className='flex flex-wrap gap-2' role='group' aria-label='状態で絞り込み'>
                {(
                  [
                    { id: '', label: 'すべて' },
                    { id: 'draft', label: '下書き' },
                    { id: 'published', label: '公開中' },
                    { id: 'closed', label: '受付終了' },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id || 'all'}
                    type='button'
                    onClick={() => setStatusFilter(t.id)}
                    className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                      statusFilter === t.id
                        ? 'border-blue-900 bg-blue-50 text-blue-900'
                        : 'border-solid-gray-420 text-solid-gray-700'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {isLoading ? (
                <p className='text-solid-gray-600'>読み込み中...</p>
              ) : loadError ? (
                <p className='text-error-1' role='alert'>
                  {loadError}
                </p>
              ) : forms.filter((f) => !statusFilter || f.status === statusFilter).length === 0 ? (
                <p className='text-solid-gray-600'>
                  {forms.length === 0 ? 'まだフォームがありません。' : 'この状態のフォームはありません。'}
                </p>
              ) : (
                <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                  {forms.filter((f) => !statusFilter || f.status === statusFilter).map((f) => (
                    <li key={f.id} className='py-3'>
                      <Link
                        to={`/patchform/${f.id}`}
                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                      >
                        {f.title}
                      </Link>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        {statusLabel[f.status] || f.status} /{' '}
                        {new Date(f.updated_at).toLocaleString('ja-JP')}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
