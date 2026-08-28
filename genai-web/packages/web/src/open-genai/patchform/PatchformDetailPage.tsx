import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { FormTagList } from './FormTagsField';
import { PATCHFORM_LABEL } from './labels';
import { PatchformApplicationPage } from './PatchformApplicationPage';
import { PatchformApplyPage } from './PatchformApplyPage';
import { PatchformInboxPage } from './PatchformInboxPage';
import { PatchformProceduresPage } from './PatchformProceduresPage';
import { PatchformSubnav } from './PatchformSubnav';
import { FillForm } from './runtime/FillForm';
import { missingRequired } from './runtime/visibility';
import {
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  uploadPatchformFile,
  usePatchformActions,
  usePatchformApplication,
  usePatchformApplicationImiSources,
  usePatchformDetail,
} from './usePatchform';
import { sourcesFromApplication } from './runtime/imiSuggest';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
  closed: '受付終了',
  archived: 'アーカイブ',
};

const workLabel = (locked?: boolean, workStatus?: string | null) =>
  locked || workStatus === 'ready' ? '作成完了' : '作成中';

const visLabel: Record<string, string> = {
  internal: '庁内のみ',
  public: '外部のみ',
  both: '庁内と外部',
};

export const PatchformDetailPage = () => {
  const { formId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const applicationToken = searchParams.get('app') || '';
  const applicationItemId = searchParams.get('item') || '';
  const fromMy = searchParams.get('from') === 'my';
  const { form, isLoading, loadError, mutate } = usePatchformDetail(formId);
  const { application } = usePatchformApplication(applicationToken || undefined);
  // 本人の他プロジェクトの記入済み様式から横断候補を取り込む（庁内のみ）。
  const { sources: crossSources } = usePatchformApplicationImiSources(
    fromMy ? application?.id : undefined,
  );
  const {
    setStatus,
    remove,
    submitAnswers,
    loadDraft,
    submitting,
    error,
    setError,
  } = usePatchformActions();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [submitterName, setSubmitterName] = useState('');
  const [pane, setPane] = useState<'overview' | 'fill'>(applicationToken ? 'fill' : 'overview');
  const [wizardLast, setWizardLast] = useState(true);
  const [draftNote, setDraftNote] = useState<string | null>(null);
  const canEdit = Boolean(form?.can_edit);
  const alreadySubmitted = Boolean(form?.my_submitted && form.allow_multiple === false);
  const isReception = form?.kind === 'reception' || Boolean(form?.source_form_id);
  const isDefinition = !isReception;
  const canFill =
    isReception &&
    Boolean(applicationToken) &&
    form?.status === 'published' &&
    form.visibility !== 'public' &&
    !alreadySubmitted;
  const fillDef = form?.fill_definition ?? form?.definition;

  useEffect(() => {
    if (isReception && form?.source_form_id && !applicationToken) {
      navigate(`/patchform/${form.source_form_id}`, { replace: true });
    }
  }, [isReception, form?.source_form_id, applicationToken, navigate]);

  useEffect(() => {
    if (!formId || !form?.allow_draft || !canFill) return;
    void loadDraft(formId).then((draft) => {
      if (!draft?.receipt_code) return;
      setAnswers(draft.answers ?? {});
      if (draft.submitter_name) setSubmitterName(draft.submitter_name);
      setDraftNote('前回の下書きを復元しました。');
    });
  }, [formId, form?.allow_draft, canFill, loadDraft]);

  const onStatus = async (status: string, extra?: { locked?: boolean }) => {
    if (!formId) return;
    setError(null);
    const detail = await setStatus(formId, status, extra);
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
      application_token: applicationToken || undefined,
      application_item_id: applicationItemId || undefined,
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
      application_token: applicationToken || undefined,
      application_item_id: applicationItemId || undefined,
    });
    if (ok) {
      setAnswers({});
      setDraftNote(null);
      await mutate();
      if (ok.application) {
        navigate(
          `/patchform/applications/${ok.application.id}${fromMy ? '?from=my' : ''}`,
        );
        return;
      }
      navigate(fromMy ? '/patchform/my' : '/patchform/inbox');
    }
  };

  if (formId === 'procedures') {
    return <PatchformProceduresPage />;
  }
  if (formId === 'inbox') {
    return <PatchformInboxPage />;
  }
  if (formId === 'applications') {
    return <PatchformApplicationPage />;
  }
  if (formId === 'apply') {
    return <PatchformApplyPage />;
  }

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
        {form && isReception && !applicationToken ? (
          <p className='text-solid-gray-600'>フォーム定義へ移動しています...</p>
        ) : null}
        {form && !(isReception && !applicationToken) && (
          <>
            <div className='flex flex-col gap-2'>
              <h1 className='text-std-20B-160 lg:text-std-24B-150'>{form.title}</h1>
              {applicationToken ? null : <FormTagList tags={form.tags} />}
              {applicationToken ? null : <PatchformSubnav current='forms' />}
              <p className='text-std-16N-170 text-solid-gray-700'>
                {applicationToken
                  ? '必要事項を記入して送信してください。'
                  : isReception
                    ? `${statusLabel[form.status]} · ${visLabel[form.visibility]}`
                    : `${workLabel(form.locked, form.work_status)} · ${visLabel[form.visibility]}`}
              </p>
              {form.description && (
                <p className='text-std-16N-170 text-solid-gray-700'>{form.description}</p>
              )}
            </div>
            {applicationToken ? null : (
            <div className='flex flex-wrap gap-2'>
              {canEdit && (
              <Link to={`/patchform/${form.id}/edit`} className='inline-flex'>
                <Button type='button' variant='outline' size='sm'>
                  編集
                </Button>
              </Link>
              )}
              {canEdit && isDefinition && !form.locked && (
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={submitting}
                  onClick={() => onStatus('draft', { locked: true })}
                >
                  作成完了
                </Button>
              )}
              {canEdit && isDefinition && form.locked && (
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={submitting}
                  onClick={() => onStatus('draft', { locked: false })}
                >
                  作成に戻す
                </Button>
              )}
              {form.can_delete && isDefinition ? (
              <Button type='button' variant='text' size='sm' onClick={onDelete}>
                削除
              </Button>
              ) : null}
            </div>
            )}
            {applicationToken ? null : error && (
              <p className='text-error-1' role='alert'>
                {error}
              </p>
            )}
            {applicationToken || !(canFill || alreadySubmitted) ? null : (
            <div className='flex flex-wrap gap-2 border-b border-solid-gray-300' role='tablist' aria-label='詳細の表示'>
              {(
                [
                  { id: 'overview', label: '概要' },
                  { id: 'fill', label: '回答する' },
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
            )}

            {pane === 'overview' && !applicationToken && (
              <dl className='grid max-w-xl grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-std-16N-170'>
                {[
                  { term: '保持期間', desc: `${form.retention_days} 日` },
                  { term: '部品数', desc: `${form.definition.components.length}` },
                  ...(form.has_pin ? [{ term: '暗証番号', desc: '外部回答にあり' }] : []),
                  { term: '下書き保存', desc: form.allow_draft === false ? '不可' : '可' },
                  { term: '同じ人の再提出', desc: form.allow_multiple === false ? '不可' : '可' },
                  {
                    term: '回答者',
                    desc:
                      form.identity_mode === 'required'
                        ? '申請（記名必須）'
                        : form.identity_mode === 'anonymous'
                          ? '匿名'
                          : '任意記名',
                  },
                ].map((row) => (
                  <div key={row.term} className='contents'>
                    <dt className='text-solid-gray-600'>{row.term}</dt>
                    <dd className='text-solid-gray-900'>{row.desc}</dd>
                  </div>
                ))}
              </dl>
            )}

            {(pane === 'fill' || applicationToken) && alreadySubmitted && (
              <section className='rounded-8 border border-solid-gray-300 p-4'>
                <p className='text-std-16N-170'>このフォームにはすでに回答しています。</p>
              </section>
            )}

            {(pane === 'fill' || applicationToken) && canFill && fillDef && (
              <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
                <h2 className='text-std-18B-160'>{applicationToken ? form.title : '庁内から回答する'}</h2>
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
                  imiSources={[
                    ...sourcesFromApplication(application, form.id),
                    ...crossSources,
                  ]}
                  prepareItems={application?.notice?.prepare || []}
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

          </>
        )}
      </div>
    </LayoutBody>
  );
};
