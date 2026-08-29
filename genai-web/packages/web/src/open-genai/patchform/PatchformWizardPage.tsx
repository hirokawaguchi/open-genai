import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import {
  PiCheckCircleFill,
  PiFileTextBold,
  PiPaperclipBold,
  PiSignpostBold,
} from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { DOCMAKER_LABEL } from '../docmaker/labels';
import { FillForm } from './runtime/FillForm';
import { missingRequired } from './runtime/visibility';
import { omitsNavigation } from './types';
import type { FormComponent, FormDefinition, ProcedureResolvePreview, SlotKind } from './types';
import {
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  resolveProcedurePreview,
  uploadPatchformFile,
  usePatchformActions,
  usePatchformApplication,
  usePatchformDetail,
  usePatchformProcedure,
  usePatchformProjectActions,
} from './usePatchform';

type Step = 'intro' | 'conditions' | 'preview';

const STEPS: { id: Step; label: string }[] = [
  { id: 'intro', label: 'はじめに' },
  { id: 'conditions', label: '申請条件' },
  { id: 'preview', label: '必要書類の確認' },
];

const kindIcon = (kind: SlotKind) => {
  if (kind === 'attach') return <PiPaperclipBold className='size-4 text-solid-gray-600' />;
  if (kind === 'data') return <PiSignpostBold className='size-4 text-blue-900' />;
  return <PiFileTextBold className='size-4 text-solid-gray-600' />;
};

const requiredLabel: Record<string, string> = {
  required: '必須',
  recommended: '推奨',
  optional: '任意',
};

// 装飾・表示専用の部品（設問ではない）。これらは次の設問と同じステップに載せる。
const NON_FIELD_TYPES = new Set([
  'page_break',
  'divider',
  'section',
  'heading',
  'note',
  'paragraph',
  'html',
  'text_display',
  'image_display',
  'calculated',
]);

/**
 * 案内フォームを「1問ずつ」進むウィザードに変換する。
 * 案内フォームには通常 page_break が無く、そのままだと通常の申請フォームと同じ
 * フラット表示になってしまう。設問の前に page_break を差し込み、FillForm の
 * ウィザードモード（進捗バー・前へ/次へ）で1設問ずつ提示して区別する。
 */
const withStepBreaks = (definition: FormDefinition): FormDefinition => {
  const out: FormComponent[] = [];
  let pageHasField = false;
  let idx = 0;
  for (const c of definition.components) {
    const isField = !NON_FIELD_TYPES.has(c.type);
    if (isField && pageHasField) {
      out.push({ id: `__wiz_break_${idx++}`, type: 'page_break', label: '' });
      pageHasField = false;
    }
    out.push(c);
    if (isField) pageHasField = true;
  }
  return { ...definition, components: out };
};

/**
 * プロジェクト作成ウィザード（庁内）。
 * docmaker.net の「申請パック（案内＋ひな型）を使って案件を新規作成する」体験を再現する。
 * 案内フォーム（ナビ）を通常の申請フォームと切り離し、
 * 「はじめに → 申請条件 → 必要書類の確認」の順に案内する。確定すると
 * 空のプロジェクトを作成し、案内回答を反映して提出書類一覧を初期化する。
 */
export const PatchformWizardPage = () => {
  const { procedureId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  // ?app=<applicationId> があれば「既存プロジェクトの条件を変更」モード。
  const editAppId = searchParams.get('app') || '';
  const { procedure, isLoading: procLoading, loadError: procError } =
    usePatchformProcedure(procedureId);
  const guideFormId = procedure?.guide_reception_id || procedure?.guide_form_id;
  const { form: guideForm, isLoading: guideLoading } = usePatchformDetail(guideFormId);
  const { application: editApp } = usePatchformApplication(editAppId || undefined);
  const { create } = usePatchformProjectActions();
  const { submitAnswers } = usePatchformActions();

  const [step, setStep] = useState<Step>('intro');
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  // 既存プロジェクトの回答を初期値へ流し込む（1回だけ）。
  const prefilled = useRef(false);
  useEffect(() => {
    if (prefilled.current || !editAppId || !editApp) return;
    const nav = editApp.items.find((it) => it.kind === 'data') ?? editApp.items[0];
    if (nav?.answers && Object.keys(nav.answers).length > 0) {
      setAnswers({ ...nav.answers });
    }
    prefilled.current = true;
  }, [editAppId, editApp]);
  const [wizardLast, setWizardLast] = useState(true);
  const [preview, setPreview] = useState<ProcedureResolvePreview | null>(null);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fillDef = guideForm?.fill_definition ?? guideForm?.definition;
  const hasQuestions = (fillDef?.components?.length ?? 0) > 0;
  // 条件変更モードでは「はじめに」を飛ばして条件選択から始める。
  const jumped = useRef(false);
  useEffect(() => {
    if (jumped.current || !editAppId || !hasQuestions) return;
    if (step === 'intro') setStep('conditions');
    jumped.current = true;
  }, [editAppId, hasQuestions, step]);
  // 1問ずつのステップに変換した定義（ウィザード表示用）。
  const wizardDef = useMemo(() => (fillDef ? withStepBreaks(fillDef) : undefined), [fillDef]);
  const published = procedure?.status === 'published';
  // 選択肢のない「申請用紙1枚」の手続きは、ウィザードにせず素の申請フォームとして
  // 記入・送信させる（案内の分岐が無いため書類一覧の事前確認も不要）。
  const singleForm = Boolean(procedure && omitsNavigation(procedure));
  // 単一フォームでは「はじめに」を飛ばして記入から始める。
  const jumpedSingle = useRef(false);
  useEffect(() => {
    if (jumpedSingle.current || !singleForm) return;
    if (step === 'intro') setStep('conditions');
    jumpedSingle.current = true;
  }, [singleForm, step]);

  const stepIndex = useMemo(() => STEPS.findIndex((s) => s.id === step), [step]);

  const goPreview = async () => {
    if (!procedureId || !fillDef) return;
    const missing = missingRequired(fillDef.components, answers);
    if (missing) {
      setError(`${missing.label}は必須です`);
      return;
    }
    setError(null);
    setBusy(true);
    const res = await resolveProcedurePreview(procedureId, answers);
    setBusy(false);
    // 解決 API が未反映でもウィザードは止めない（作成後に案内から書類が並ぶ）。
    setPreview(res);
    setPreviewUnavailable(res === null);
    setStep('preview');
  };

  const cancelTo = editAppId
    ? `/patchform/applications/${editAppId}?from=my`
    : '/docmaker';

  // 単一フォーム: 必須チェックのうえ、そのまま案件を作成して申請フォームを保存する。
  const onSubmitSingle = async () => {
    if (!fillDef) return;
    const missing = missingRequired(fillDef.components, answers);
    if (missing) {
      setError(`${missing.label}は必須です`);
      return;
    }
    await onConfirm();
  };

  const onConfirm = async () => {
    if (!procedureId) return;
    setError(null);
    setBusy(true);
    // 既存プロジェクトの条件変更: 新規作成せず、案内回答だけ差し替える。
    if (editAppId && editApp) {
      const nav = editApp.items.find((it) => it.kind === 'data') ?? editApp.items[0];
      if (nav?.form_id) {
        const ok = await submitAnswers(nav.form_id, {
          answers,
          application_token: editApp.token,
          application_item_id: nav.id,
        });
        if (!ok) {
          setBusy(false);
          setError('案内の反映に失敗しました。');
          return;
        }
      }
      setBusy(false);
      navigate(`/patchform/applications/${editApp.id}?from=my`);
      return;
    }
    const created = await create(procedureId);
    if (!created) {
      setBusy(false);
      setError('手続きの作成に失敗しました。');
      return;
    }
    const nav = created.items.find((it) => it.kind === 'data') ?? created.items[0];
    if (nav?.form_id) {
      const ok = await submitAnswers(nav.form_id, {
        answers,
        application_token: created.token,
        application_item_id: nav.id,
      });
      if (!ok) {
        // プロジェクトは作成済み。案内の反映だけ失敗しても作業台へ進める。
        setBusy(false);
        navigate(`/patchform/applications/${created.id}?from=my`);
        return;
      }
    }
    setBusy(false);
    navigate(`/patchform/applications/${created.id}?from=my`);
  };

  return (
    <LayoutBody>
      <PageTitle title={`${procedure?.name || '手続き'}を始める | ${DOCMAKER_LABEL}`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: DOCMAKER_LABEL, to: '/docmaker' },
            ...(editAppId
              ? [
                  {
                    label: editApp?.title || procedure?.name || '手続き',
                    to: `/patchform/applications/${editAppId}?from=my`,
                  },
                  { label: '条件を変更' },
                ]
              : [{ label: `${procedure?.name || '手続き'}を始める` }]),
          ]}
        />

        <div className='flex flex-col gap-2'>
          <h1 className='flex items-center gap-2 text-std-20B-160 lg:text-std-24B-150'>
            {singleForm ? (
              <PiFileTextBold className='size-6 text-blue-900' />
            ) : (
              <PiSignpostBold className='size-6 text-blue-900' />
            )}
            {singleForm
              ? procedure?.name || '手続き'
              : editAppId
                ? '申請条件を変更'
                : `${procedure?.name || '手続き'}を始める`}
          </h1>
          <p className='text-std-16N-170 text-solid-gray-700'>
            {singleForm
              ? '必要事項を記入して送信してください。'
              : editAppId
                ? '案内の回答を選び直すと、必要な書類の一覧が更新されます（追加済みの書類はそのまま残ります）。'
                : '案内に沿って条件を選ぶと、この手続きに必要な書類の一覧（申請パック）を用意します。'}
          </p>
        </div>

        {/* ステッパー（単一フォームでは出さない） */}
        {!singleForm ? (
        <ol className='flex flex-wrap items-center gap-2'>
          {STEPS.map((s, i) => {
            const state = i < stepIndex ? 'done' : i === stepIndex ? 'current' : 'todo';
            return (
              <li key={s.id} className='flex items-center gap-2'>
                <span
                  className={`flex size-6 items-center justify-center rounded-full text-dns-14N-130 ${
                    state === 'current'
                      ? 'bg-blue-900 text-white'
                      : state === 'done'
                        ? 'bg-green-600 text-white'
                        : 'bg-solid-gray-200 text-solid-gray-600'
                  }`}
                >
                  {state === 'done' ? '✓' : i + 1}
                </span>
                <span
                  className={`text-std-16N-170 ${
                    state === 'current' ? 'font-bold text-blue-900' : 'text-solid-gray-600'
                  }`}
                >
                  {s.label}
                </span>
                {i < STEPS.length - 1 ? (
                  <span className='mx-1 text-solid-gray-400'>›</span>
                ) : null}
              </li>
            );
          })}
        </ol>
        ) : null}

        {(procLoading || guideLoading) && <p className='text-solid-gray-600'>読み込み中...</p>}
        {procError && (
          <p className='text-error-1' role='alert'>
            {procError}
          </p>
        )}
        {procedure && !published ? (
          <p className='text-solid-gray-700'>この手続きは受付していません。</p>
        ) : null}

        {error && (
          <p className='text-error-1' role='alert'>
            {error}
          </p>
        )}

        {procedure && published ? (
          <>
            {step === 'intro' && (
              <section className='flex flex-col gap-4 rounded-8 border border-solid-gray-300 p-4'>
                {procedure.description ? (
                  <p className='text-std-16N-170 text-solid-gray-800'>{procedure.description}</p>
                ) : null}
                <ul className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
                  <li className='flex items-start gap-2'>
                    <PiSignpostBold className='mt-0.5 size-5 text-blue-900' />
                    案内の質問に答えると、あなたの申請に必要な書類だけを揃えます。
                  </li>
                  <li className='flex items-start gap-2'>
                    <PiFileTextBold className='mt-0.5 size-5 text-solid-gray-600' />
                    書類はオンライン記入・ひな型のダウンロード・ファイル添付のいずれでも準備できます。
                  </li>
                  <li className='flex items-start gap-2'>
                    <PiCheckCircleFill className='mt-0.5 size-5 text-green-600' />
                    作成後は「マイ手続き」で保存され、少しずつ進められます。
                  </li>
                </ul>
                <div className='flex flex-wrap gap-2'>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    onClick={() => setStep(hasQuestions ? 'conditions' : 'preview')}
                  >
                    はじめる
                  </Button>
                  <Link to={cancelTo} className='inline-flex'>
                    <Button type='button' variant='outline' size='md'>
                      やめる
                    </Button>
                  </Link>
                </div>
              </section>
            )}

            {step === 'conditions' && singleForm && (
              <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
                {fillDef ? (
                  <FillForm
                    definition={fillDef}
                    values={answers}
                    onChange={(id, v) => setAnswers((p) => ({ ...p, [id]: v }))}
                    onExtract={extractPatchformFile}
                    onUpload={(file, kind) =>
                      guideFormId
                        ? uploadPatchformFile(guideFormId, file, kind)
                        : Promise.reject(new Error('準備中です'))
                    }
                    onPostalLookup={lookupPatchformPostal}
                    onCorporateLookup={lookupPatchformCorporate}
                  />
                ) : null}
                <div className='flex flex-wrap gap-2'>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    aria-disabled={busy}
                    onClick={() => void onSubmitSingle()}
                  >
                    {busy ? '送信中...' : '送信する'}
                  </Button>
                  <Link to={cancelTo} className='inline-flex'>
                    <Button type='button' variant='outline' size='md'>
                      やめる
                    </Button>
                  </Link>
                </div>
              </section>
            )}

            {step === 'conditions' && !singleForm && (
              <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
                <h2 className='flex items-center gap-2 text-std-18B-160'>
                  <PiSignpostBold className='size-5 text-blue-900' />
                  申請条件を選ぶ
                </h2>
                <p className='text-std-16N-170 text-solid-gray-700'>
                  次の質問に答えてください。回答に応じて必要な書類が変わります。
                </p>
                {wizardDef ? (
                  <FillForm
                    definition={wizardDef}
                    values={answers}
                    onChange={(id, v) => setAnswers((p) => ({ ...p, [id]: v }))}
                    onExtract={extractPatchformFile}
                    onUpload={(file, kind) =>
                      guideFormId
                        ? uploadPatchformFile(guideFormId, file, kind)
                        : Promise.reject(new Error('準備中です'))
                    }
                    onPostalLookup={lookupPatchformPostal}
                    onCorporateLookup={lookupPatchformCorporate}
                    onWizardChange={(info) => setWizardLast(info.isLast)}
                  />
                ) : null}
                {wizardLast ? (
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      type='button'
                      variant='solid-fill'
                      size='md'
                      aria-disabled={busy}
                      onClick={() => void goPreview()}
                    >
                      {busy ? '確認中...' : '必要書類を確認'}
                    </Button>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      onClick={() => navigate(cancelTo)}
                    >
                      やめる
                    </Button>
                  </div>
                ) : null}
              </section>
            )}

            {step === 'preview' && (
              <section className='flex flex-col gap-4 rounded-8 border border-solid-gray-300 p-4'>
                <h2 className='flex items-center gap-2 text-std-18B-160'>
                  <PiFileTextBold className='size-5 text-solid-gray-700' />
                  この申請に必要な書類（{preview?.count ?? 0}件）
                </h2>
                {previewUnavailable && (
                  <p className='rounded-8 bg-solid-gray-50 p-3 text-dns-14N-130 text-solid-gray-700'>
                    必要書類の事前確認は利用できませんでした。このまま作成すると、案内の回答に応じて提出書類一覧が作られます。
                  </p>
                )}
                {preview && preview.items.length > 0 ? (
                  <ul className='divide-y divide-solid-gray-200 rounded-8 border border-solid-gray-300'>
                    {preview.items.map((it) => (
                      <li key={it.slot_id} className='flex items-center gap-3 px-3 py-2'>
                        {kindIcon(it.kind)}
                        <div className='min-w-0 flex-1'>
                          <p className='truncate text-std-16N-170 text-solid-gray-900'>
                            {it.title}
                            {it.cardinality === 'many' ? (
                              <span className='ml-2 text-dns-14N-130 text-solid-gray-500'>
                                （複数可）
                              </span>
                            ) : null}
                          </p>
                          <p className='text-dns-14N-130 text-solid-gray-500'>
                            {[
                              requiredLabel[it.required] || it.required,
                              it.can_fill_online ? 'オンライン記入可' : null,
                              it.has_template ? 'ひな型あり' : null,
                            ]
                              .filter(Boolean)
                              .join(' / ')}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className='text-std-16N-170 text-solid-gray-700'>
                    必要な書類は作成後に案内から追加できます。
                  </p>
                )}
                {preview?.notice?.prepare && preview.notice.prepare.length > 0 ? (
                  <div className='rounded-8 bg-solid-gray-50 p-3'>
                    <p className='text-dns-14B-130 text-solid-gray-700'>あらかじめ用意するもの</p>
                    <ul className='mt-1 list-disc pl-5 text-dns-14N-130 text-solid-gray-700'>
                      {preview.notice.prepare.map((p, i) => (
                        <li key={i}>{p}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className='flex flex-wrap gap-2'>
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    onClick={() => setStep(hasQuestions ? 'conditions' : 'intro')}
                  >
                    戻る
                  </Button>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    aria-disabled={busy}
                    onClick={() => void onConfirm()}
                  >
                    {busy
                      ? editAppId
                        ? '更新中...'
                        : '作成中...'
                      : editAppId
                        ? 'この条件に更新'
                        : 'この内容で手続きを作成'}
                  </Button>
                </div>
              </section>
            )}
          </>
        ) : null}

        <p className='text-std-16N-170'>
          <Link to='/docmaker' className='text-blue-900 underline-offset-2 hover:underline'>
            マイ手続きへ
          </Link>
        </p>
      </div>
    </LayoutBody>
  );
};
