import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { FillForm } from './runtime/FillForm';
import { answerRows } from './runtime/formatAnswer';
import { missingRequired } from './runtime/visibility';
import {
  downloadPatchformCarrier,
  downloadPatchformCsv,
  downloadPatchformFile,
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  uploadPatchformFile,
  usePatchformActions,
  usePatchformAssist,
  usePatchformAudit,
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
  const { submissions, mutate: mutateSubs } = usePatchformSubmissions(
    form?.can_view_submissions ? formId : undefined,
  );
  const {
    setStatus,
    remove,
    submitAnswers,
    loadDraft,
    setWithdrawn,
    revealSubmission,
    submitting,
    error,
    setError,
  } = usePatchformActions();
  const { events: auditEvents, mutate: mutateAudit } = usePatchformAudit(
    formId && form?.has_mynumber && form.can_view_submissions ? formId : undefined,
  );
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [submitterName, setSubmitterName] = useState('');
  const [revealed, setRevealed] = useState<Record<string, Record<string, unknown>>>({});
  const {
    draftInvite,
    busy: inviteBusy,
    error: inviteError,
  } = usePatchformAssist();
  const [invite, setInvite] = useState<{ subject: string; body: string } | null>(null);
  const [pane, setPane] = useState<'overview' | 'fill' | 'answers' | 'audit'>('overview');
  const [wizardLast, setWizardLast] = useState(true);
  const [openReceipt, setOpenReceipt] = useState<string | null>(null);
  const [draftNote, setDraftNote] = useState<string | null>(null);
  const canEdit = Boolean(form?.can_edit);
  const canViewAnswers = Boolean(form?.can_view_submissions);
  const alreadySubmitted = Boolean(form?.my_submitted && form.allow_multiple === false);
  const canFill =
    form?.status === 'published' && form.visibility !== 'public' && !alreadySubmitted;
  const fillDef = form?.fill_definition ?? form?.definition;

  useEffect(() => {
    if (!formId || !form?.allow_draft || !canFill) return;
    void loadDraft(formId).then((draft) => {
      if (!draft?.receipt_code) return;
      setAnswers(draft.answers ?? {});
      if (draft.submitter_name) setSubmitterName(draft.submitter_name);
      setDraftNote('前回の下書きを復元しました。');
    });
  }, [formId, form?.allow_draft, canFill, loadDraft]);

  const confirmPublish = () => {
    if (!form) return true;
    const n = form.submission_count ?? 0;
    if (n <= 0) return true;
    const nextVer = (form.published_version ?? 0) + 1;
    return window.confirm(
      `回答が ${n} 件あります。第${nextVer}版として公開します。\n\n` +
        'これから答える人には、いま保存されている部品構成が見えます。\n' +
        'これまでの回答は、答えた当時の版のまま残ります。\n\nよろしいですか？',
    );
  };

  const onStatus = async (status: string) => {
    if (!formId) return;
    if (status === 'published' && !confirmPublish()) return;
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

  const onSaveDraft = async () => {
    if (!formId || !form) return;
    setDraftNote(null);
    const ok = await submitAnswers(formId, {
      answers,
      submitter_name: submitterName.trim() || undefined,
      is_draft: true,
    });
    if (ok) {
      setDraftNote('下書きを保存しました。あとから続きを入力できます。');
    }
  };

  const onSubmit = async () => {
    if (!formId || !form || !fillDef) return;
    const missing = missingRequired(fillDef.components, answers);
    if (missing) {
      setError(`${missing.label}は必須です`);
      return;
    }
    const ok = await submitAnswers(formId, {
      answers,
      submitter_name: submitterName.trim() || undefined,
    });
    if (ok) {
      setAnswers({});
      setDraftNote(null);
      await mutate();
      await mutateSubs();
      if (canViewAnswers) setPane('answers');
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
              {canEdit && (
              <Link to={`/patchform/${form.id}/edit`}>
                <Button type='button' variant='outline' size='sm'>
                  編集
                </Button>
              </Link>
              )}
              {canEdit && form.status === 'draft' && (
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
              {canEdit && form.status === 'published' && form.draft_differs && (
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  aria-disabled={submitting}
                  onClick={() => onStatus('published')}
                >
                  公開版に反映
                </Button>
              )}
              {canEdit && form.status === 'published' && (
                <Button type='button' variant='outline' size='sm' onClick={() => onStatus('closed')}>
                  受付を終了
                </Button>
              )}
              {canEdit && form.status === 'closed' && (
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
              {form.can_delete ? (
              <Button type='button' variant='text' size='sm' onClick={onDelete}>
                削除
              </Button>
              ) : null}
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
                  ...(canFill || alreadySubmitted ? [{ id: 'fill', label: '回答する' } as const] : []),
                  ...(canViewAnswers
                    ? [
                        {
                          id: 'answers',
                          label: `回答（${submissions.filter((s) => !s.withdrawn).length}）`,
                        } as const,
                      ]
                    : []),
                  ...(form.has_mynumber && canViewAnswers
                    ? [{ id: 'audit', label: '個人番号の監査' } as const]
                    : []),
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

            {canEdit && form.draft_differs && (form.status === 'published' || form.status === 'closed') && (
              <p className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3 text-std-16N-170 text-solid-gray-800'>
                下書きの部品構成が、直近の第{form.published_version}版と違います。
                回答者に見せるには「{form.status === 'closed' ? '再公開する' : '公開版に反映'}」が必要です。
                {(form.submission_count ?? 0) > 0
                  ? ` 既存の回答 ${form.submission_count} 件は、当時の版のまま残ります。`
                  : ''}
              </p>
            )}

            {pane === 'overview' && (
              <section className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
                <p>保持期間: {form.retention_days} 日</p>
                <p>部品数: {form.definition.components.length}</p>
                <p>
                  回答: {form.submission_count ?? 0} 件
                  {(form.withdrawn_count ?? 0) > 0 ? `（取下げ ${form.withdrawn_count} 件）` : ''}
                </p>
                {form.published_version != null ? (
                  <p>公開版: 第{form.published_version}版</p>
                ) : (
                  <p>公開版: まだありません</p>
                )}
                {form.has_pin && <p>外部回答に暗証番号あり</p>}
                <p>下書き保存: {form.allow_draft === false ? '不可' : '可'}</p>
                <p>同じ人の再提出: {form.allow_multiple === false ? '不可' : '可'}</p>
                <p>
                  回答者:{' '}
                  {form.identity_mode === 'required'
                    ? '申請（記名必須）'
                    : form.identity_mode === 'anonymous'
                      ? '匿名'
                      : '任意記名'}
                </p>
              </section>
            )}

            {pane === 'fill' && alreadySubmitted && (
              <section className='rounded-8 border border-solid-gray-300 p-4'>
                <p className='text-std-16N-170'>このフォームにはすでに回答しています。</p>
              </section>
            )}

            {pane === 'fill' && canFill && fillDef && (
              <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
                <h2 className='text-std-18B-160'>庁内から回答する</h2>
                {form.identity_mode === 'required' && !form.has_name_composite ? (
                  <p className='text-std-16N-170 text-solid-gray-700'>
                    ログイン中の利用者として記録します。
                  </p>
                ) : null}
                {form.identity_mode === 'optional' && !form.has_name_composite ? (
                <div>
                  <Label htmlFor='pf-sname' size='sm'>
                    回答者名（任意。空なら匿名）
                  </Label>
                  <input
                    id='pf-sname'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={submitterName}
                    onChange={(e) => setSubmitterName(e.target.value)}
                  />
                </div>
                ) : null}
                {form.identity_mode === 'anonymous' ? (
                  <p className='text-std-16N-170 text-solid-gray-700'>
                    このフォームは匿名です。名前や職員名は記録しません。
                  </p>
                ) : null}
                {draftNote && (
                  <p className='text-std-16N-170 text-solid-gray-700'>{draftNote}</p>
                )}
                <FillForm
                  definition={fillDef}
                  values={answers}
                  onChange={(id, v) => setAnswers((p) => ({ ...p, [id]: v }))}
                  onExtract={extractPatchformFile}
                  onUpload={(file, kind) => uploadPatchformFile(form.id, file, kind)}
                  onPostalLookup={lookupPatchformPostal}
                  onCorporateLookup={lookupPatchformCorporate}
                  onWizardChange={(info) => setWizardLast(info.isLast)}
                />
                {error && (
                  <p className='text-error-1' role='alert'>
                    {error}
                  </p>
                )}
                {wizardLast ? (
                  <div className='flex flex-wrap gap-2'>
                    {form.allow_draft !== false && (
                      <Button
                        type='button'
                        variant='outline'
                        size='md'
                        aria-disabled={submitting}
                        onClick={() => void onSaveDraft()}
                      >
                        {submitting ? '保存中...' : '下書きを保存'}
                      </Button>
                    )}
                    <Button type='button' variant='solid-fill' size='md' aria-disabled={submitting} onClick={onSubmit}>
                      {submitting ? '送信中...' : '回答を送信'}
                    </Button>
                  </div>
                ) : null}
              </section>
            )}

            {pane === 'answers' && canViewAnswers && (
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
                  {form.can_reveal && (
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      onClick={() => {
                        if (
                          window.confirm(
                            '個人番号を含めて書き出します。操作は監査ログに残ります。よろしいですか？',
                          )
                        ) {
                          void downloadPatchformCsv(form.id, 'csv', true).then(() => mutateAudit());
                        }
                      }}
                    >
                      個人番号を含めてCSV
                    </Button>
                  )}
                </div>
                {submissions.length === 0 ? (
                  <p className='text-solid-gray-600'>まだ回答がありません。</p>
                ) : (
                  <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                    {submissions.map((s) => {
                      const comps = s.definition?.components ?? form.definition.components;
                      const shown = { ...s.answers, ...(revealed[s.id] || {}) };
                      const rows = answerRows(comps, shown);
                      const open = openReceipt === s.id;
                      return (
                        <li key={s.id} className='py-3 text-std-16N-170'>
                          <button
                            type='button'
                            className='w-full text-left'
                            onClick={() => setOpenReceipt(open ? null : s.id)}
                          >
                            <p className='text-std-16B-150'>
                              {s.withdrawn ? '取下げ / ' : ''}
                              {s.respondent_label || s.submitter_name || s.receipt_code} / 控え{' '}
                              {s.receipt_code}
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
                            <>
                            <dl className='mt-2 grid gap-2 rounded-8 bg-solid-gray-50 p-3'>
                              {form.can_reveal && !revealed[s.id] ? (
                                <div className='md:col-span-2'>
                                  <button
                                    type='button'
                                    className='text-blue-900 underline'
                                    onClick={() => {
                                      if (
                                        !window.confirm(
                                          '個人番号を表示します。操作は監査ログに残ります。よろしいですか？',
                                        )
                                      ) {
                                        return;
                                      }
                                      void revealSubmission(form.id, s.id).then((item) => {
                                        if (item?.answers) {
                                          setRevealed((p) => ({ ...p, [s.id]: item.answers }));
                                          void mutateAudit();
                                        }
                                      });
                                    }}
                                  >
                                    個人番号を表示
                                  </button>
                                </div>
                              ) : null}
                              {rows.map((row) => {
                                const raw = shown[row.id];
                                const rec =
                                  raw && typeof raw === 'object' && !Array.isArray(raw)
                                    ? (raw as { file_id?: string; filename?: string })
                                    : null;
                                const fileId = rec?.file_id;
                                return (
                                  <div key={row.id}>
                                    <dt className='text-dns-14N-130 text-solid-gray-600'>{row.label}</dt>
                                    <dd className='whitespace-pre-wrap'>
                                      {fileId ? (
                                        <button
                                          type='button'
                                          className='text-blue-900 underline'
                                          onClick={() =>
                                            void downloadPatchformFile(
                                              form.id,
                                              fileId,
                                              rec?.filename || row.value,
                                            )
                                          }
                                        >
                                          {row.value}
                                        </button>
                                      ) : (
                                        row.value
                                      )}
                                    </dd>
                                  </div>
                                );
                              })}
                            </dl>
                            <div className='mt-2'>
                              <Button
                                type='button'
                                variant='outline'
                                size='sm'
                                aria-disabled={submitting}
                                onClick={() => {
                                  const next = !s.withdrawn;
                                  const ok = window.confirm(
                                    next
                                      ? 'この回答を取り下げますか。内容は残ります。'
                                      : '取下げを取り消して受付に戻しますか。',
                                  );
                                  if (!ok) return;
                                  void setWithdrawn(form.id, s.id, next).then((done) => {
                                    if (done) {
                                      void mutateSubs();
                                      void mutate();
                                    }
                                  });
                                }}
                              >
                                {s.withdrawn ? '受付に戻す' : '取り下げる'}
                              </Button>
                            </div>
                            </>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            )}

            {pane === 'audit' && (
              <section className='flex flex-col gap-3'>
                <p className='text-std-16N-170 text-solid-gray-700'>
                  個人番号の表示と、番号を含む書き出しの記録です。
                </p>
                {auditEvents.length === 0 ? (
                  <p className='text-solid-gray-600'>まだ記録はありません。</p>
                ) : (
                  <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                    {auditEvents.map((ev) => (
                      <li key={ev.id} className='py-3 text-std-16N-170'>
                        <p className='text-std-16B-150'>
                          {ev.action === 'reveal' ? '個人番号を表示' : '個人番号を含めて書き出し'}
                        </p>
                        <p className='text-dns-14N-130 text-solid-gray-600'>
                          {ev.actor_user_id} · {new Date(ev.created_at).toLocaleString('ja-JP')}
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
