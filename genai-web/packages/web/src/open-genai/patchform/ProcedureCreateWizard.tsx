import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { NAVIGATION_TAG } from './labels';
import type { FormDefinition, FormSummary, Procedure, ProcedureRule } from './types';
import { usePatchformDetail, usePatchformList, usePatchformProcedureActions } from './usePatchform';

type StartMode = 'omit' | 'navigate';
type StepId = 'basics' | 'form' | 'docs';

type Answer = {
  key: string;
  componentId: string;
  question: string;
  option: string;
  label: string;
};

type Doc = {
  kind: 'yoshiki' | 'attach';
  formId?: string;
  name: string;
};

const CHOICE_TYPES = new Set(['select', 'radio', 'checkbox']);

const optionItems = (raw: unknown): { value: string; label: string }[] => {
  let list: unknown[] = [];
  if (typeof raw === 'string') {
    list = raw
      .replace(/\r\n/g, '\n')
      .split('\n')
      .map((part) => part.trim())
      .filter(Boolean);
  } else if (Array.isArray(raw)) {
    list = raw;
  } else {
    return [];
  }
  const out: { value: string; label: string }[] = [];
  const seen = new Set<string>();
  for (const item of list) {
    let value = '';
    let label = '';
    if (typeof item === 'string') {
      const text = item.trim();
      const bar = text.indexOf('|');
      if (bar >= 0) {
        label = text.slice(0, bar).trim();
        value = text.slice(bar + 1).trim();
      } else {
        label = value = text;
      }
    } else if (item && typeof item === 'object') {
      const row = item as { value?: unknown; label?: unknown };
      value = String(row.value || row.label || '').trim();
      label = String(row.label || row.value || '').trim();
    }
    if (!value && label) value = label;
    if (!label && value) label = value;
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label });
  }
  return out;
};

const choiceAnswers = (definition: FormDefinition | undefined): Answer[] => {
  const comps = definition?.components || [];
  const answers: Answer[] = [];
  for (const comp of comps) {
    if (!CHOICE_TYPES.has(comp.type)) continue;
    const componentId = (comp.id || '').trim();
    if (!componentId) continue;
    const items = optionItems(comp.properties?.options);
    for (const item of items) {
      answers.push({
        key: `${componentId}\t${item.value}`,
        componentId,
        question: comp.label || componentId,
        option: item.value,
        label: item.label,
      });
    }
  }
  return answers;
};

const formOptionLabel = (form: FormSummary) => {
  const state = form.locked || form.work_status === 'ready' ? '作成完了' : '作成中';
  const opening = form.has_opening ? ' · 受付中' : '';
  return `${form.title}（${state}${opening}）`;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (procedure: Procedure) => void;
};

export const ProcedureCreateWizard = ({ open, onClose, onCreated }: Props) => {
  const { forms } = usePatchformList();
  const { create, submitting, error, setError } = usePatchformProcedureActions();
  const [step, setStep] = useState<StepId>('basics');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<StartMode>('omit');
  const [guideFormId, setGuideFormId] = useState('');
  const [docs, setDocs] = useState<Record<string, Doc[]>>({});
  const [answerKey, setAnswerKey] = useState('');
  const [addFormId, setAddFormId] = useState('');
  const [attachName, setAttachName] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  const { form: guideForm, isLoading: guideLoading, loadError: guideError } = usePatchformDetail(
    open && guideFormId ? guideFormId : undefined,
  );

  useEffect(() => {
    if (!open) return;
    setStep('basics');
    setName('');
    setDescription('');
    setMode('omit');
    setGuideFormId('');
    setDocs({});
    setAnswerKey('');
    setAddFormId('');
    setAttachName('');
    setLocalError(null);
    setError(null);
  }, [open, setError]);

  const isNavForm = (form: FormSummary) => (form.tags || []).includes(NAVIGATION_TAG);
  const selectableForms = forms.filter(
    (form) => form.status !== 'archived' && (mode === 'omit' ? !isNavForm(form) : isNavForm(form)),
  );
  const styleForms = forms.filter(
    (form) =>
      form.status !== 'archived' && form.id !== guideFormId && !isNavForm(form),
  );
  const answers = useMemo(
    () => choiceAnswers(guideForm?.definition),
    [guideForm?.definition],
  );
  const needsDocs = mode === 'navigate' && answers.length > 0;
  const formSettled = Boolean(guideFormId) && !guideLoading;
  const expectDocs = mode === 'navigate' && !(formSettled && answers.length === 0);
  const steps: StepId[] = expectDocs ? ['basics', 'form', 'docs'] : ['basics', 'form'];
  const stepIndex = Math.max(0, steps.indexOf(step));
  const stepTitle =
    step === 'basics' ? '名前を決める' : step === 'form' ? '用紙を選ぶ' : '出す書類を足す';
  const selectedAnswer = answers.find((answer) => answer.key === answerKey) || answers[0];
  const selectedDocs = selectedAnswer ? docs[selectedAnswer.key] || [] : [];

  const chooseMode = (next: StartMode) => {
    setMode(next);
    const keep = forms.find((form) => form.id === guideFormId);
    const ok = keep && (next === 'omit' ? !isNavForm(keep) : isNavForm(keep));
    if (!ok) setGuideFormId('');
    setDocs({});
    setLocalError(null);
  };

  const addYoshiki = () => {
    if (!selectedAnswer || !addFormId) return;
    const form = styleForms.find((item) => item.id === addFormId);
    if (!form) return;
    setDocs((prev) => {
      const current = prev[selectedAnswer.key] || [];
      if (current.some((doc) => doc.kind === 'yoshiki' && doc.formId === form.id)) return prev;
      return {
        ...prev,
        [selectedAnswer.key]: [...current, { kind: 'yoshiki', formId: form.id, name: form.title }],
      };
    });
    setAddFormId('');
  };

  const addAttach = () => {
    const title = attachName.trim();
    if (!selectedAnswer || !title) return;
    setDocs((prev) => {
      const current = prev[selectedAnswer.key] || [];
      if (current.some((doc) => doc.kind === 'attach' && doc.name === title)) return prev;
      return {
        ...prev,
        [selectedAnswer.key]: [...current, { kind: 'attach', name: title }],
      };
    });
    setAttachName('');
  };

  const removeDoc = (index: number) => {
    if (!selectedAnswer) return;
    setDocs((prev) => ({
      ...prev,
      [selectedAnswer.key]: (prev[selectedAnswer.key] || []).filter((_, i) => i !== index),
    }));
  };

  const finish = async () => {
    setLocalError(null);
    setError(null);
    if (!name.trim() || !guideFormId) {
      setLocalError(mode === 'omit' ? '名前と申請フォームを選んでください。' : '名前とナビゲーションフォームを選んでください。');
      return;
    }
    const rules: ProcedureRule[] = [];
    if (needsDocs) {
      for (const answer of answers) {
        const items = docs[answer.key] || [];
        if (items.length === 0) continue;
        rules.push({
          component_id: answer.componentId,
          option: answer.option,
          form_ids: items
            .filter((doc) => doc.kind === 'yoshiki' && doc.formId)
            .map((doc) => doc.formId as string),
          prepare: items.filter((doc) => doc.kind === 'attach').map((doc) => doc.name),
          notes: '',
        });
      }
    }
    const created = await create({
      name: name.trim(),
      description: description.trim() || undefined,
      guide_form_id: guideFormId,
      ...(rules.length ? { mapping: { rules } } : {}),
    });
    if (created) onCreated(created);
  };

  const goNext = () => {
    setLocalError(null);
    if (step === 'basics') {
      if (!name.trim()) {
        setLocalError('名前を入力してください。');
        return;
      }
      setStep('form');
      return;
    }
    if (step === 'form') {
      if (!guideFormId) {
        setLocalError(mode === 'omit' ? '申請フォームを選んでください。' : 'ナビゲーションフォームを選んでください。');
        return;
      }
      if (mode === 'navigate' && guideLoading) return;
      if (mode === 'navigate' && answers.length > 0) {
        setAnswerKey(answers[0]?.key || '');
        setStep('docs');
        return;
      }
      void finish();
    }
  };

  const goBack = () => {
    setLocalError(null);
    if (step === 'docs') setStep('form');
    else if (step === 'form') setStep('basics');
  };

  const shownError = localError || error;
  const formReady = Boolean(guideFormId) && (mode === 'omit' || !guideLoading);
  const formStepIsLast =
    step === 'form' &&
    Boolean(guideFormId) &&
    !guideLoading &&
    (mode === 'omit' || answers.length === 0);
  const lastAction = step === 'docs' || formStepIsLast;

  return (
    <CustomDialog isOpen={open} onClose={onClose} position='top'>
      <CustomDialogPanel className='max-w-3xl'>
        <CustomDialogHeader hasClose={true} onClose={onClose}>
          新しい手続き
        </CustomDialogHeader>
        <CustomDialogBody>
          <p className='text-dns-16N-130 text-solid-gray-600'>
            手順 {stepIndex + 1} / {steps.length}　{stepTitle}
          </p>
          <p className='mt-1 text-std-16N-170 text-solid-gray-700'>
            {step === 'basics'
              ? '庁内の一覧に出る名前と、申請用紙が1枚か、答えによって書類が変わるかを決めます。'
              : step === 'form'
                ? mode === 'omit'
                  ? 'この手続きで使う申請用紙を1枚選びます。'
                  : '申請者が最初に答えるナビゲーションフォームを選びます。'
                : 'この答えのときに出す書類だけを足します。審査項目は、作成したあとの編集画面で書きます。'}
          </p>

          {step === 'basics' ? (
            <div className='mt-4 flex flex-col gap-4'>
              <div>
                <Label htmlFor='pf-wiz-name' size='sm'>
                  名前
                </Label>
                <input
                  id='pf-wiz-name'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder='例: 転入の手続き'
                  required
                />
              </div>
              <div>
                <Label htmlFor='pf-wiz-desc' size='sm'>
                  説明（任意）
                </Label>
                <textarea
                  id='pf-wiz-desc'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder='例: 転入・転居のときに出す書類を振り分けます'
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>職員向けのメモです。空欄でも構いません。</p>
              </div>
              <fieldset>
                <legend className='text-std-16B-150'>始め方</legend>
                <div className='mt-2 flex flex-col gap-2'>
                  <label className='flex items-start gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-wiz-start'
                      className='mt-1'
                      checked={mode === 'omit'}
                      onChange={() => chooseMode('omit')}
                    />
                    <span>
                      申請用紙は1枚
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                        ナビゲーションは使いません。
                      </span>
                    </span>
                  </label>
                  <label className='flex items-start gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-wiz-start'
                      className='mt-1'
                      checked={mode === 'navigate'}
                      onChange={() => chooseMode('navigate')}
                    />
                    <span>
                      答えによって書類が変わる
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                        ナビゲーションフォームの答えごとに、出す書類を変えます。
                      </span>
                    </span>
                  </label>
                </div>
              </fieldset>
            </div>
          ) : null}

          {step === 'form' ? (
            <div className='mt-4 flex flex-col gap-3'>
              {forms.length === 0 ? (
                <div className='flex flex-col items-start gap-3'>
                  <p className='text-std-16N-170 text-solid-gray-700'>
                    まだ選べるフォームがありません。先にフォームを作成してください。
                  </p>
                  <Button asChild variant='solid-fill' size='md'>
                    <Link to='/patchform?tab=new'>フォームを作成する</Link>
                  </Button>
                </div>
              ) : (
                <>
                  <div>
                    <Label htmlFor='pf-wiz-guide' size='sm'>
                      {mode === 'omit' ? '申請フォーム' : 'ナビゲーションフォーム'}
                    </Label>
                    <select
                      id='pf-wiz-guide'
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                      value={guideFormId}
                      onChange={(e) => {
                        setGuideFormId(e.target.value);
                        setDocs({});
                        setLocalError(null);
                      }}
                    >
                      <option value=''>
                        {mode === 'omit' ? '申請フォームを選ぶ' : 'ナビゲーションフォームを選ぶ'}
                      </option>
                      {selectableForms.map((form) => (
                        <option key={form.id} value={form.id}>
                          {formOptionLabel(form)}
                        </option>
                      ))}
                    </select>
                  </div>
                  {selectableForms.length === 0 ? (
                    <div className='flex flex-col items-start gap-2'>
                      <p className='text-std-16N-170 text-solid-gray-700'>
                        {mode === 'omit'
                          ? '選べる申請フォームがありません。'
                          : '選べるナビゲーションフォームがありません。'}
                      </p>
                      <Button asChild variant='outline' size='sm'>
                        <Link to={mode === 'omit' ? '/patchform?tab=new' : '/patchform?kind=navigation&tab=new'}>
                          フォームを作成する
                        </Link>
                      </Button>
                    </div>
                  ) : null}
                  {guideFormId && guideLoading ? (
                    <p className='text-solid-gray-600'>用紙を読み込んでいます...</p>
                  ) : null}
                  {guideError ? (
                    <p className='text-error-1' role='alert'>
                      {guideError}
                    </p>
                  ) : null}
                  {mode === 'navigate' && guideForm && !guideLoading && answers.length === 0 ? (
                    <p className='text-std-16N-170 text-solid-gray-700'>
                      このフォームにラジオやプルダウンがありません。申請用紙1枚の手続きとして作成します。
                    </p>
                  ) : null}
                </>
              )}
            </div>
          ) : null}

          {step === 'docs' && selectedAnswer ? (
            <div className='mt-4 flex flex-col gap-4'>
              <div className='flex flex-wrap gap-2' role='tablist' aria-label='答え'>
                {answers.map((answer) => {
                  const count = (docs[answer.key] || []).length;
                  const selected = answer.key === selectedAnswer.key;
                  return (
                    <button
                      key={answer.key}
                      type='button'
                      role='tab'
                      aria-selected={selected}
                      onClick={() => {
                        setAnswerKey(answer.key);
                        setAddFormId('');
                        setAttachName('');
                      }}
                      className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                        selected
                          ? 'border-blue-900 bg-blue-50 text-blue-900'
                          : 'border-solid-gray-420 text-solid-gray-700'
                      }`}
                    >
                      {answer.question} {answer.label}
                      {count > 0 ? `（${count}）` : ''}
                    </button>
                  );
                })}
              </div>
              <div>
                <p className='text-std-16B-150'>「{selectedAnswer.label}」のときに出す書類</p>
                {selectedDocs.length === 0 ? (
                  <p className='mt-1 text-dns-16N-130 text-solid-gray-600'>まだ書類がありません。</p>
                ) : (
                  <ul className='mt-2 flex flex-col gap-2'>
                    {selectedDocs.map((doc, index) => (
                      <li
                        key={`${doc.kind}-${doc.formId || doc.name}`}
                        className='flex items-center justify-between gap-2 rounded-4 border border-solid-gray-300 px-3 py-2'
                      >
                        <span className='text-std-16N-170'>
                          {doc.name}
                          <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>
                            {doc.kind === 'attach' ? '添付' : '様式'}
                          </span>
                        </span>
                        <Button type='button' variant='outline' size='sm' onClick={() => removeDoc(index)}>
                          外す
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className='flex flex-wrap items-end gap-2'>
                <div className='min-w-[12rem] flex-1'>
                  <Label htmlFor='pf-wiz-yoshiki' size='sm'>
                    様式を足す
                  </Label>
                  <select
                    id='pf-wiz-yoshiki'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    value={addFormId}
                    onChange={(e) => setAddFormId(e.target.value)}
                  >
                    <option value=''>用紙を選ぶ</option>
                    {styleForms.map((form) => (
                      <option key={form.id} value={form.id}>
                        {form.title}
                      </option>
                    ))}
                  </select>
                </div>
                <Button type='button' variant='outline' size='md' aria-disabled={!addFormId} onClick={addYoshiki}>
                  足す
                </Button>
              </div>
              <div className='flex flex-wrap items-end gap-2'>
                <div className='min-w-[12rem] flex-1'>
                  <Label htmlFor='pf-wiz-attach' size='sm'>
                    添付を足す
                  </Label>
                  <input
                    id='pf-wiz-attach'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    value={attachName}
                    onChange={(e) => setAttachName(e.target.value)}
                    placeholder='例: 勤務証明書'
                  />
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='md'
                  aria-disabled={!attachName.trim()}
                  onClick={addAttach}
                >
                  足す
                </Button>
              </div>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                空のままでも作成できます。書類と審査項目は編集画面で足せます。
              </p>
            </div>
          ) : null}

          {shownError ? (
            <p className='mt-4 text-error-1' role='alert'>
              {shownError}
            </p>
          ) : null}

          <div className='mt-6 flex flex-wrap items-center justify-between gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={step === 'basics' || submitting}
              onClick={goBack}
            >
              戻る
            </Button>
            {lastAction ? (
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={submitting || !formReady || !name.trim()}
                onClick={() => void finish()}
              >
                {submitting ? '作成中...' : '作成して編集する'}
              </Button>
            ) : (
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={
                  step === 'form' &&
                  (selectableForms.length === 0 || (Boolean(guideFormId) && guideLoading))
                }
                onClick={goNext}
              >
                次へ
              </Button>
            )}
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
