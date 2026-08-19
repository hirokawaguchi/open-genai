import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { FillForm } from './runtime/FillForm';
import { answerRows } from './runtime/formatAnswer';
import {
  downloadPatchformCarrier,
  downloadPatchformCsv,
  extractPatchformFile,
  usePatchformActions,
  usePatchformAssist,
  usePatchformDetail,
  usePatchformSubmissions,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
  closed: '受付終了',
  archived: 'アーカイブ',
};

const visLabel: Record<string, string> = {
  internal: '庁内のみ',
  public: '外部のみ',
  both: '庁内と外部',
};

const formVersionLabel = (
  formVersion: number | null | undefined,
  publishedAt: string | null | undefined,
  currentVersion?: number | null,
) => {
  if (formVersion == null) return '版不明';
  const tag = currentVersion != null && formVersion === currentVersion ? '現行' : '当時';
  const when = publishedAt ? new Date(publishedAt).toLocaleString('ja-JP') : '';
  return when ? `第${formVersion}版（${tag} · ${when} 公開）` : `第${formVersion}版（${tag}）`;
};

export const PatchformDetailPage = () => {
  const { formId } = useParams();
  const navigate = useNavigate();
  const { form, isLoading, loadError, mutate } = usePatchformDetail(formId);
  const { submissions, mutate: mutateSubs } = usePatchformSubmissions(formId);
  const { setStatus, remove, submitAnswers, submitting, error, setError } = usePatchformActions();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [submitterName, setSubmitterName] = useState('');
  const {
    draftInvite,
    busy: inviteBusy,
    error: inviteError,
  } = usePatchformAssist();
  const [invite, setInvite] = useState<{ subject: string; body: string } | null>(null);
  const [pane, setPane] = useState<'overview' | 'fill' | 'answers'>('overview');
  const [openReceipt, setOpenReceipt] = useState<string | null>(null);
  const canFill = form?.status === 'published' && form.visibility !== 'public';

  const onStatus = async (status: string) => {
    if (!formId) return;
    setError(null);
    const detail = await setStatus(formId, status);
    if (detail) await mutate();
  };

  const onDelete = async () => {
    if (!formId) return;
    if (!window.confirm('このフォームを削除しますか？回答も消えます。')) return;
    const ok = await remove(formId);
    if (ok) navigate('/patchform');
  };

  const onSubmit = async () => {
    if (!formId) return;
    const ok = await submitAnswers(formId, {
      answers,
      submitter_name: submitterName.trim() || undefined,
    });
    if (ok) {
      setAnswers({});
      await mutateSubs();
      setPane('answers');
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={form?.title || PATCHFORM_LABEL} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: form?.title || '詳細' },
          ]}
        />
        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}
        {form && (
          <>
            <div className='flex flex-col gap-2'>
              <h1 className='text-std-20B-160 lg:text-std-24B-150'>{form.title}</h1>
              <p className='text-std-16N-170 text-solid-gray-700'>
                {statusLabel[form.status]} / {visLabel[form.visibility]}
              </p>
              {form.description && (
                <p className='text-std-16N-170 text-solid-gray-700'>{form.description}</p>
              )}
            </div>
            <div className='flex flex-wrap gap-2'>
              <Link to={`/patchform/${form.id}/edit`}>
                <Button type='button' variant='outline' size='sm'>
                  編集
                </Button>
              </Link>
              {form.status !== 'published' && (
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  aria-disabled={submitting}
                  onClick={() => onStatus('published')}
                >
                  公開する
                </Button>
              )}
              {form.status === 'published' && (
                <Button type='button' variant='outline' size='sm' onClick={() => onStatus('closed')}>
                  受付を終了
                </Button>
              )}
              {form.status === 'closed' && (
                <Button type='button' variant='outline' size='sm' onClick={() => onStatus('published')}>
                  再公開する
                </Button>
              )}
              {form.visibility !== 'internal' && (
                <>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={() => downloadPatchformCarrier(form.id, 'txt')}
                  >
                    リンクファイル
                  </Button>
                  <span className='self-center text-dns-14N-130 text-solid-gray-600'>
                    {form.public_url}
                  </span>
                </>
              )}
              <Button type='button' variant='text' size='sm' onClick={onDelete}>
                削除
              </Button>
              {form.visibility !== 'internal' && (
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={inviteBusy}
                  onClick={async () => {
                    const res = await draftInvite({
                      title: form.title,
                      public_url: form.public_url,
                    });
                    if (res) setInvite({ subject: res.subject, body: res.body });
                  }}
                >
                  {inviteBusy ? '作成中...' : '案内文を下書き'}
                </Button>
              )}
            </div>
            {inviteError && (
              <p className='text-error-1' role='alert'>
                {inviteError}
              </p>
            )}
            {invite && (
              <section className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                <h2 className='text-std-18B-160'>{invite.subject}</h2>
                <pre className='mt-2 whitespace-pre-wrap text-std-16N-170'>{invite.body}</pre>
              </section>
            )}

            <div className='flex flex-wrap gap-2 border-b border-solid-gray-300' role='tablist' aria-label='詳細の表示'>
              {(
                [
                  { id: 'overview', label: '概要' },
                  ...(canFill ? [{ id: 'fill', label: '回答する' } as const] : []),
                  { id: 'answers', label: `回答（${submissions.length}）` },
                ] as const
              ).map((t) => (
                <button
                  key={t.id}
                  type='button'
                  role='tab'
                  aria-selected={pane === t.id}
                  onClick={() => setPane(t.id)}
                  className={`-mb-px border-b-2 px-4 py-2 text-oln-16B-100 ${
                    pane === t.id
                      ? 'border-blue-900 text-blue-900'
                      : 'border-transparent text-solid-gray-600 hover:text-solid-gray-900'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {pane === 'overview' && (
              <section className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
                <p>保持期間: {form.retention_days} 日</p>
                <p>部品数: {form.definition.components.length}</p>
                {form.published_version != null ? (
                  <p>公開版: 第{form.published_version}版</p>
                ) : (
                  <p>公開版: まだありません</p>
                )}
                {form.has_pin && <p>外部回答に暗証番号あり</p>}
              </section>
            )}

            {pane === 'fill' && canFill && (
              <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
                <h2 className='text-std-18B-160'>庁内から回答する</h2>
                <div>
                  <Label htmlFor='pf-sname' size='sm'>
                    回答者名（任意）
                  </Label>
                  <input
                    id='pf-sname'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={submitterName}
                    onChange={(e) => setSubmitterName(e.target.value)}
                  />
                </div>
                <FillForm
                  definition={form.definition}
                  values={answers}
                  onChange={(id, v) => setAnswers((p) => ({ ...p, [id]: v }))}
                  onExtract={extractPatchformFile}
                />
                {error && (
                  <p className='text-error-1' role='alert'>
                    {error}
                  </p>
                )}
                <div>
                  <Button type='button' variant='solid-fill' size='md' aria-disabled={submitting} onClick={onSubmit}>
                    {submitting ? '送信中...' : '回答を送信'}
                  </Button>
                </div>
              </section>
            )}

            {pane === 'answers' && (
              <section className='flex flex-col gap-3'>
                <div className='flex flex-wrap items-center justify-end gap-2'>
                  <Button type='button' variant='outline' size='sm' onClick={() => downloadPatchformCsv(form.id)}>
                    CSV出力
                  </Button>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={() => downloadPatchformCsv(form.id, 'jsonl')}
                  >
                    JSONL出力
                  </Button>
                </div>
                {submissions.length === 0 ? (
                  <p className='text-solid-gray-600'>まだ回答がありません。</p>
                ) : (
                  <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                    {submissions.map((s) => {
                      const comps = s.definition?.components ?? form.definition.components;
                      const rows = answerRows(comps, s.answers);
                      const open = openReceipt === s.id;
                      return (
                        <li key={s.id} className='py-3 text-std-16N-170'>
                          <button
                            type='button'
                            className='w-full text-left'
                            onClick={() => setOpenReceipt(open ? null : s.id)}
                          >
                            <p className='text-std-16B-150'>
                              {s.submitter_name || '（無名）'} / 控え {s.receipt_code}
                            </p>
                            <p className='text-dns-14N-130 text-solid-gray-600'>
                              {formVersionLabel(s.form_version, s.published_at, form.published_version)}
                            </p>
                            <p className='text-dns-14N-130 text-solid-gray-600'>
                              {new Date(s.created_at).toLocaleString('ja-JP')}
                              {open ? ' · 閉じる' : ' · 内容を見る'}
                            </p>
                          </button>
                          {open && (
                            <dl className='mt-2 grid gap-2 rounded-8 bg-solid-gray-50 p-3'>
                              {rows.map((row) => (
                                <div key={row.id}>
                                  <dt className='text-dns-14N-130 text-solid-gray-600'>{row.label}</dt>
                                  <dd className='whitespace-pre-wrap'>{row.value}</dd>
                                </div>
                              ))}
                            </dl>
                          )}
                        </li>
                      );
                    })}
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
