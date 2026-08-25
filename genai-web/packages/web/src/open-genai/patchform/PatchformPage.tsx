import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { PiBookOpenBold, PiListBold, PiNotePencilBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { FormTagList, FormTagsField } from './FormTagsField';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformPaneTabs } from './PatchformPaneTabs';
import { PatchformSubnav } from './PatchformSubnav';
import {
  usePatchformActions,
  usePatchformAssist,
  usePatchformConfig,
  usePatchformList,
} from './usePatchform';

const workLabel = (locked?: boolean, workStatus?: string | null) =>
  locked || workStatus === 'ready' ? '作成完了' : '作成中';

/**
 * フォーム専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["patchform"] 未起動時は有効化手順を案内する。
 */
export const PatchformPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fromGuideLink = searchParams.get('intent') === 'guide';
  const pane = searchParams.get('tab') === 'new' || fromGuideLink ? 'new' : 'list';
  const { config, isLoading: configLoading, unavailable } = usePatchformConfig();
  const { forms, isLoading, loadError, mutate } = usePatchformList();
  const { create, submitting, error, setError } = usePatchformActions();
  const {
    generate,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const [formKind, setFormKind] = useState<'application' | 'navigation'>(
    fromGuideLink ? 'navigation' : 'application',
  );
  const asGuide = formKind === 'navigation';
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [aiText, setAiText] = useState('');
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [tags, setTags] = useState<string[]>(fromGuideLink ? [NAVIGATION_TAG] : []);
  const knownTags = [...new Set(forms.flatMap((f) => f.tags || []))].sort();

  const chooseKind = (kind: 'application' | 'navigation') => {
    setFormKind(kind);
    setTags((prev) => {
      const without = prev.filter((t) => t !== NAVIGATION_TAG);
      return kind === 'navigation' ? [NAVIGATION_TAG, ...without] : without;
    });
  };

  useEffect(() => {
    if (pane !== 'new') return;
    document.getElementById('pf-title')?.focus();
  }, [pane]);

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
      tags,
    });
    if (detail) {
      await mutate();
      navigate(asGuide ? `/patchform/${detail.id}/edit?intent=guide` : `/patchform/${detail.id}/edit`);
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
          <PatchformSubnav current='forms' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            フォームを作成することができます。「一覧」で作成したフォームを見ることができます。「作成」で申請フォームやナビゲーションフォームの作成ができます。
          </p>
          <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
            <DisclosureSummary>
              <span className='flex items-center text-std-16B-150'>
                <PiBookOpenBold className='mr-2 size-5 flex-none' />
                使い方（クリックで開閉）
              </span>
            </DisclosureSummary>
            <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
              <p>・タイトルを付けて作成し、編集画面で部品を並べます。1枚だけの手続きではタグは不要です。答えで用紙を足すナビゲーションフォームには、ラジオやプルダウンを入れ、「ナビゲーション」タグを付けてください。</p>
              <p>・受付は「手続き」を公開すると始まります。届いた件は「申請受付」にあります。</p>
              <p>・外部 URL は「手続きを公開」にあります。LGWAN から届かない場合は、そこのリンクファイルを持ち出して別端末で開いてください。</p>
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
            <PatchformPaneTabs
              label='フォームの作成と一覧'
              current={pane}
              tabs={[
                { id: 'list', label: `一覧（${forms.length}）`, to: '/patchform', icon: PiListBold },
                {
                  id: 'new',
                  label: '作成',
                  to: fromGuideLink ? '/patchform?tab=new&intent=guide' : '/patchform?tab=new',
                  icon: PiNotePencilBold,
                },
              ]}
            />
            {pane === 'new' ? (
            <section id='pf-new-form' className='flex flex-col gap-4'>
              <h2 className='flex items-center gap-2 text-std-18B-160'>
                <PiNotePencilBold className='size-5' />
                新しいフォーム
              </h2>
              <form onSubmit={onSubmit} className='flex flex-col gap-4'>
                <fieldset>
                  <legend className='text-std-16B-150'>種類</legend>
                  <div className='mt-2 flex flex-col gap-2'>
                    <label className='flex items-start gap-2 text-std-16N-170'>
                      <input
                        type='radio'
                        name='pf-form-kind'
                        className='mt-1'
                        checked={!asGuide}
                        onChange={() => chooseKind('application')}
                      />
                      <span>
                        申請フォームを作る
                        <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                          1枚の申請やお問い合わせなど、記入してもらう用紙です。
                        </span>
                      </span>
                    </label>
                    <label className='flex items-start gap-2 text-std-16N-170'>
                      <input
                        type='radio'
                        name='pf-form-kind'
                        className='mt-1'
                        checked={asGuide}
                        onChange={() => chooseKind('navigation')}
                      />
                      <span>
                        ナビゲーションフォームを作る
                        <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                          申請者の状況を聞き、必要な申請フォームの組み合わせを決めます。ラジオやプルダウンを入れてください。
                        </span>
                      </span>
                    </label>
                  </div>
                </fieldset>
                <div>
                  <Label htmlFor='pf-title' size='sm'>
                    タイトル
                  </Label>
                  <input
                    id='pf-title'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={asGuide ? '例: 転入・転居の確認' : '例: 転入届'}
                    required
                  />
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    一覧と入力画面の見出しに出ます。
                  </p>
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
                    placeholder='例: 転入か転居かを確認します'
                  />
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    入力画面の案内文です。空欄でも構いません。
                  </p>
                </div>
                <FormTagsField
                  id='pf-tags'
                  value={tags}
                  onChange={setTags}
                  suggestions={knownTags}
                />
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
                          tags,
                        });
                        if (created) {
                          await mutate();
                          navigate(
                            asGuide
                              ? `/patchform/${created.id}/edit?intent=guide`
                              : `/patchform/${created.id}/edit`,
                          );
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
            ) : (
            <section className='flex flex-col gap-3'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <h2 className='text-std-18B-160'>フォーム一覧</h2>
                <Link to='/patchform?tab=new' className='inline-flex'>
                  <Button type='button' variant='solid-fill' size='sm'>
                    新しいフォームを作る
                  </Button>
                </Link>
              </div>
              <div className='flex flex-wrap gap-2' role='group' aria-label='状態で絞り込み'>
                {(
                  [
                    { id: '', label: 'すべて' },
                    { id: 'editing', label: '作成中' },
                    { id: 'ready', label: '作成完了' },
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
              {knownTags.length > 0 ? (
                <div className='flex flex-wrap gap-2' role='group' aria-label='タグで絞り込み'>
                  <button
                    type='button'
                    onClick={() => setTagFilter('')}
                    className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                      tagFilter === ''
                        ? 'border-blue-900 bg-blue-50 text-blue-900'
                        : 'border-solid-gray-420 text-solid-gray-700'
                    }`}
                  >
                    すべてのタグ
                  </button>
                  {knownTags.map((tag) => (
                    <button
                      key={tag}
                      type='button'
                      onClick={() => setTagFilter(tag)}
                      className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                        tagFilter === tag
                          ? 'border-blue-900 bg-blue-50 text-blue-900'
                          : 'border-solid-gray-420 text-solid-gray-700'
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              ) : null}
              {isLoading ? (
                <p className='text-solid-gray-600'>読み込み中...</p>
              ) : loadError ? (
                <p className='text-error-1' role='alert'>
                  {loadError}
                </p>
              ) : forms.filter((f) => {
                  if (statusFilter) {
                    const ready = Boolean(f.locked || f.work_status === 'ready');
                    if (statusFilter === 'ready' ? !ready : ready) return false;
                  }
                  if (tagFilter && !(f.tags || []).includes(tagFilter)) return false;
                  return true;
                }).length === 0 ? (
                <p className='text-solid-gray-600'>
                  {forms.length === 0 ? (
                    <>
                      まだフォームがありません。
                      <Link
                        to='/patchform?tab=new'
                        className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                      >
                        作成タブから作る
                      </Link>
                    </>
                  ) : (
                    'この条件のフォームはありません。'
                  )}
                </p>
              ) : (
                <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                  {forms.filter((f) => {
                    if (statusFilter) {
                      const ready = Boolean(f.locked || f.work_status === 'ready');
                      if (statusFilter === 'ready' ? !ready : ready) return false;
                    }
                    if (tagFilter && !(f.tags || []).includes(tagFilter)) return false;
                    return true;
                  }).map((f) => (
                    <li key={f.id} className='py-3'>
                      <Link
                        to={`/patchform/${f.id}`}
                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                      >
                        {f.title}
                      </Link>
                      <FormTagList tags={f.tags} />
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        {workLabel(f.locked, f.work_status)}
                        {f.has_opening ? ' / 受付中' : ''}
                        {(f.reception_count ?? 0) > 0 ? ` / 窓口 ${f.reception_count} 回` : ''}
                        {f.role === 'editor'
                          ? ' / 編集者'
                          : f.role === 'viewer'
                            ? ' / 閲覧者'
                            : f.role === 'respondent'
                              ? ' / 回答'
                              : ''}
                        {' / '}
                        {new Date(f.updated_at).toLocaleString('ja-JP')}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};
