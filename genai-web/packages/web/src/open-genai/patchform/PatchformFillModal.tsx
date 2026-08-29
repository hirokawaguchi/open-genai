import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { FillForm } from './runtime/FillForm';
import { sourcesFromApplication } from './runtime/imiSuggest';
import { missingRequired } from './runtime/visibility';
import type { Application } from './types';
import {
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  uploadPatchformFile,
  usePatchformActions,
  usePatchformApplicationImiSources,
  usePatchformDetail,
} from './usePatchform';

type Props = {
  open: boolean;
  formId: string;
  itemTitle: string;
  applicationToken: string;
  applicationItemId: string;
  applicationId?: string;
  application?: Application | null;
  // 提出済み／記入途中の既存回答。開いたときの初期値にする（下書きがあれば上書き）。
  initialAnswers?: Record<string, unknown> | null;
  onClose: () => void;
  onSubmitted: (updated: Application | null) => void;
};

/**
 * 申請束のワークベンチから、提出書類の1枚をその場で記入するモーダル。
 * 記入後は画面遷移せず、更新後の申請束を親に返して一覧を更新する。
 */
export const PatchformFillModal = (props: Props) => {
  const {
    open,
    formId,
    itemTitle,
    applicationToken,
    applicationItemId,
    applicationId,
    application,
    initialAnswers,
    onClose,
    onSubmitted,
  } = props;
  const { form, isLoading, loadError } = usePatchformDetail(open ? formId : undefined);
  const { sources: crossSources } = usePatchformApplicationImiSources(
    open ? applicationId : undefined,
  );
  const { submitAnswers, loadDraft, submitting, error, setError } = usePatchformActions();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [submitterName, setSubmitterName] = useState('');
  const [wizardLast, setWizardLast] = useState(true);
  const [draftNote, setDraftNote] = useState<string | null>(null);

  const fillDef = form?.fill_definition ?? form?.definition;

  // 開くたびに状態を初期化する。既存回答があれば初期値にし、下書きがあれば上書きする。
  useEffect(() => {
    if (!open) return;
    setAnswers(initialAnswers ? { ...initialAnswers } : {});
    setSubmitterName('');
    setDraftNote(null);
    setError(null);
    setWizardLast(true);
  }, [open, formId, initialAnswers, setError]);

  useEffect(() => {
    if (!open || !formId || !form?.allow_draft) return;
    void loadDraft(formId).then((draft) => {
      if (!draft?.receipt_code) return;
      setAnswers(draft.answers ?? {});
      if (draft.submitter_name) setSubmitterName(draft.submitter_name);
      setDraftNote('前回の下書きを復元しました。');
    });
  }, [open, formId, form?.allow_draft, loadDraft]);

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
    if (ok) setDraftNote('下書きを保存しました。あとから続きを入力できます。');
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
      onSubmitted(ok.application ?? null);
      onClose();
    }
  };

  return (
    <CustomDialog isOpen={open} onClose={onClose} position='top'>
      <CustomDialogPanel className='max-w-3xl'>
        <CustomDialogHeader hasClose={true} onClose={onClose}>
          {form?.title || itemTitle}
        </CustomDialogHeader>
        <CustomDialogBody>
          {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
          {loadError && (
            <p className='text-error-1' role='alert'>
              {loadError}
            </p>
          )}
          {form && fillDef ? (
            <div className='flex flex-col gap-3'>
              {form.identity_mode === 'required' && !form.has_name_composite ? (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  ログイン中の利用者として記録します。
                </p>
              ) : null}
              {form.identity_mode === 'optional' && !form.has_name_composite ? (
                <div>
                  <Label htmlFor='pf-modal-sname' size='sm'>
                    回答者名（任意。空なら匿名）
                  </Label>
                  <input
                    id='pf-modal-sname'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={submitterName}
                    onChange={(e) => setSubmitterName(e.target.value)}
                  />
                </div>
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
                  ...sourcesFromApplication(application ?? null, form.id),
                  ...crossSources,
                ]}
                prepareItems={application?.notice?.prepare || []}
              />
              {error && (
                <p className='text-error-1' role='alert'>
                  {error}
                </p>
              )}
              <div className='flex flex-wrap justify-end gap-2 border-t border-solid-gray-300 pt-3'>
                <Button type='button' variant='outline' size='md' onClick={onClose}>
                  閉じる
                </Button>
                {wizardLast && form.allow_draft !== false && (
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
                {wizardLast && (
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    aria-disabled={submitting}
                    onClick={onSubmit}
                  >
                    {submitting ? '送信中...' : '記入を保存'}
                  </Button>
                )}
              </div>
            </div>
          ) : !isLoading && !loadError ? (
            <p className='text-solid-gray-700'>この書類はオンライン記入に対応していません。</p>
          ) : null}
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
