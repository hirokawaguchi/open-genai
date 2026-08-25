import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { FillForm } from './runtime/FillForm';
import { missingRequired } from './runtime/visibility';
import {
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  uploadPatchformFile,
  usePatchformActions,
  usePatchformDetail,
  usePatchformProcedure,
} from './usePatchform';

export const PatchformApplyPage = () => {
  const { procedureId } = useParams();
  const navigate = useNavigate();
  const { procedure, isLoading: procLoading, loadError: procError } = usePatchformProcedure(procedureId);
  const receptionId = procedure?.guide_reception_id || undefined;
  const { form, isLoading: formLoading, loadError: formError, mutate } = usePatchformDetail(receptionId);
  const { submitAnswers, loadDraft, submitting, error, setError } = usePatchformActions();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [submitterName, setSubmitterName] = useState('');
  const [wizardLast, setWizardLast] = useState(true);
  const [draftNote, setDraftNote] = useState<string | null>(null);
  const fillDef = form?.fill_definition ?? form?.definition;
  const published = procedure?.status === 'published' && Boolean(receptionId);
  const alreadySubmitted = Boolean(form?.my_submitted && form.allow_multiple === false);
  const canFill = Boolean(published && form && fillDef && !alreadySubmitted);

  useEffect(() => {
    if (!receptionId || !form?.allow_draft || !canFill) return;
    void loadDraft(receptionId).then((draft) => {
      if (!draft?.receipt_code) return;
      setAnswers(draft.answers ?? {});
      if (draft.submitter_name) setSubmitterName(draft.submitter_name);
      setDraftNote('前回の下書きを復元しました。');
    });
  }, [receptionId, form?.allow_draft, canFill, loadDraft]);

  const onSaveDraft = async () => {
    if (!receptionId || !form) return;
    setDraftNote(null);
    const ok = await submitAnswers(receptionId, {
      answers,
      submitter_name: submitterName.trim() || undefined,
      is_draft: true,
    });
    if (ok) setDraftNote('下書きを保存しました。あとから続きを入力できます。');
  };

  const onSubmit = async () => {
    if (!receptionId || !form || !fillDef) return;
    const missing = missingRequired(fillDef.components, answers);
    if (missing) {
      setError(`${missing.label}は必須です`);
      return;
    }
    const ok = await submitAnswers(receptionId, {
      answers,
      submitter_name: submitterName.trim() || undefined,
    });
    if (ok) {
      setAnswers({});
      setDraftNote(null);
      await mutate();
      if (ok.application) {
        navigate(`/patchform/applications/${ok.application.id}`);
        return;
      }
      navigate('/patchform/inbox');
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={procedure?.name || '庁内申請'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '手続き', to: '/patchform/procedures' },
            { label: procedure?.name || '庁内申請' },
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>
            {procedure?.name || '庁内申請'}
          </h1>
          <p className='text-std-16N-170 text-solid-gray-700'>
            必要事項を記入して送信してください。
          </p>
        </div>
        {(procLoading || formLoading) && <p className='text-solid-gray-600'>読み込み中...</p>}
        {(procError || formError) && (
          <p className='text-error-1' role='alert'>
            {procError || formError}
          </p>
        )}
        {procedure && !published ? (
          <p className='text-solid-gray-700'>この手続きは受付していません。</p>
        ) : null}
        {alreadySubmitted ? (
          <p className='text-std-16N-170'>この手続きにはすでに回答しています。</p>
        ) : null}
        {canFill && fillDef && form ? (
          <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
            <h2 className='text-std-18B-160'>{form.title}</h2>
            {form.identity_mode === 'required' && !form.has_name_composite ? (
              <p className='text-std-16N-170 text-solid-gray-700'>
                ログイン中の利用者として記録します。
              </p>
            ) : null}
            {form.identity_mode === 'optional' && !form.has_name_composite ? (
              <div>
                <Label htmlFor='pf-apply-name' size='sm'>
                  回答者名（任意。空なら匿名）
                </Label>
                <input
                  id='pf-apply-name'
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
            {draftNote ? <p className='text-std-16N-170 text-solid-gray-700'>{draftNote}</p> : null}
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
            {error ? (
              <p className='text-error-1' role='alert'>
                {error}
              </p>
            ) : null}
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
        ) : null}
        <p className='text-std-16N-170'>
          <Link to='/patchform/procedures' className='text-blue-900 underline-offset-2 hover:underline'>
            手続き一覧へ戻る
          </Link>
        </p>
      </div>
    </LayoutBody>
  );
};
