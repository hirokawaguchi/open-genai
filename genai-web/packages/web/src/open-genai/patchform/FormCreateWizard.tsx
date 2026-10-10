import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { NAVIGATION_TAG } from './labels';
import type { FormDefinition, FormDetail } from './types';
import { usePatchformActions, usePatchformAssist, usePatchformConfig } from './usePatchform';

type Kind = 'application' | 'navigation';
type StepId = 'basics' | 'start';
type StartMode = 'blank' | 'question' | 'draft';

const newId = () => `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;

const optionLines = (raw: string): string[] => {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of raw.replace(/\r\n/g, '\n').split('\n')) {
    const text = line.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
};

const questionDefinition = (
  title: string,
  description: string,
  question: string,
  options: string[],
  version: string,
): FormDefinition => ({
  $version: version,
  metadata: { title, description, doc_role: 'yoshiki' },
  components: [
    {
      id: newId(),
      type: 'select',
      label: question,
      required: true,
      properties: { options },
    },
  ],
});

type Props = {
  open: boolean;
  kind: Kind;
  onClose: () => void;
  onCreated: (form: FormDetail) => void;
};

export const FormCreateWizard = ({ open, kind, onClose, onCreated }: Props) => {
  const { config } = usePatchformConfig();
  const { create, submitting, error, setError } = usePatchformActions();
  const { generate, busy: assistBusy, error: assistError, setError: setAssistError } = usePatchformAssist();
  const [step, setStep] = useState<StepId>('basics');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<StartMode>('blank');
  const [question, setQuestion] = useState('');
  const [optionsText, setOptionsText] = useState('');
  const [draftText, setDraftText] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep('basics');
    setTitle('');
    setDescription('');
    setMode(kind === 'navigation' ? 'question' : 'blank');
    setQuestion('');
    setOptionsText('');
    setDraftText('');
    setLocalError(null);
    setError(null);
    setAssistError(null);
  }, [open, kind, setError, setAssistError]);

  const navigation = kind === 'navigation';
  const steps: StepId[] = ['basics', 'start'];
  const stepIndex = steps.indexOf(step);
  const busy = submitting || assistBusy;
  const shownError = localError || error || assistError;

  const finish = async () => {
    setLocalError(null);
    setError(null);
    setAssistError(null);
    const name = title.trim();
    if (!name) {
      setLocalError('名前を入力してください。');
      return;
    }
    const tags = navigation ? [NAVIGATION_TAG] : [];
    const desc = description.trim() || undefined;
    if (mode === 'draft') {
      const text = draftText.trim();
      if (!text) {
        setLocalError('下書きにしたい文章を入力してください。');
        return;
      }
      const res = await generate({ text });
      if (!res) return;
      const created = await create({
        title: res.definition.metadata.title || name,
        description: res.definition.metadata.description || desc,
        definition: res.definition,
        visibility: 'internal',
        tags,
      });
      if (created) onCreated(created);
      return;
    }
    if (navigation) {
      const label = question.trim();
      const options = optionLines(optionsText);
      if (!label) {
        setLocalError('質問を入力してください。');
        return;
      }
      if (options.length < 2) {
        setLocalError('選択肢を2つ以上、1行に1つ書いてください。');
        return;
      }
      const created = await create({
        title: name,
        description: desc,
        visibility: 'internal',
        tags,
        definition: questionDefinition(
          name,
          description.trim(),
          label,
          options,
          config?.spec_version || 'opengenai-patchform/1',
        ),
      });
      if (created) onCreated(created);
      return;
    }
    const created = await create({
      title: name,
      description: desc,
      visibility: 'internal',
      tags,
    });
    if (created) onCreated(created);
  };

  return (
    <CustomDialog isOpen={open} onClose={onClose} position='top'>
      <CustomDialogPanel className='max-w-3xl'>
        <CustomDialogHeader hasClose={true} onClose={onClose}>
          {navigation ? '新しいナビゲーションフォーム' : '新しい申請フォーム'}
        </CustomDialogHeader>
        <CustomDialogBody>
          <p className='text-dns-16N-130 text-solid-gray-600'>
            手順 {stepIndex + 1} / {steps.length}　{step === 'basics' ? '名前を決める' : navigation ? '最初の質問' : '始め方'}
          </p>
          <p className='mt-1 text-std-16N-170 text-solid-gray-700'>
            {step === 'basics'
              ? navigation
                ? '申請者が最初に答える入口の名前です。できたフォームは編集画面で質問を足せます。'
                : '記入してもらう用紙の名前です。欄は、作成したあとの編集画面で足します。'
              : navigation
                ? '状況を聞く質問を1つ置きます。選択肢ごとに出す書類は、手続きの作成で決めます。'
                : '空の用紙で始めるか、文章から欄の下書きを作るかを選びます。'}
          </p>

          {step === 'basics' ? (
            <div className='mt-4 flex flex-col gap-4'>
              <div>
                <Label htmlFor='pf-form-wiz-title' size='sm'>
                  名前
                </Label>
                <input
                  id='pf-form-wiz-title'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={navigation ? '例: 転入・転居の確認' : '例: 転入届'}
                  required
                />
              </div>
              <div>
                <Label htmlFor='pf-form-wiz-desc' size='sm'>
                  説明（任意）
                </Label>
                <textarea
                  id='pf-form-wiz-desc'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={navigation ? '例: 転入か転居かを確認します' : '例: 転入の届出に使う用紙です'}
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  入力画面の案内文です。空欄でも構いません。
                </p>
              </div>
            </div>
          ) : (
            <div className='mt-4 flex flex-col gap-4'>
              <fieldset className='m-0 flex flex-col gap-2 border-0 p-0'>
                <legend className='text-dns-14N-130 text-solid-gray-700'>始め方</legend>
                {(navigation
                  ? [
                      { id: 'question' as const, label: '質問を自分で書く' },
                      { id: 'draft' as const, label: '文章から下書きを作る' },
                    ]
                  : [
                      { id: 'blank' as const, label: '空の用紙で始める' },
                      { id: 'draft' as const, label: '文章から下書きを作る' },
                    ]
                ).map((item) => (
                  <label key={item.id} className='flex items-center gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-form-wiz-mode'
                      checked={mode === item.id}
                      onChange={() => {
                        setMode(item.id);
                        setLocalError(null);
                      }}
                    />
                    {item.label}
                  </label>
                ))}
              </fieldset>
              {mode === 'question' ? (
                <>
                  <div>
                    <Label htmlFor='pf-form-wiz-q' size='sm'>
                      質問
                    </Label>
                    <input
                      id='pf-form-wiz-q'
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder='例: 届出の区分'
                    />
                  </div>
                  <div>
                    <Label htmlFor='pf-form-wiz-opts' size='sm'>
                      選択肢
                    </Label>
                    <textarea
                      id='pf-form-wiz-opts'
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                      rows={4}
                      value={optionsText}
                      onChange={(e) => setOptionsText(e.target.value)}
                      placeholder={'転入\n転居'}
                    />
                    <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>1行に1つ。2つ以上必要です。</p>
                  </div>
                </>
              ) : null}
              {mode === 'draft' ? (
                <div>
                  <Label htmlFor='pf-form-wiz-draft' size='sm'>
                    下書きにしたい文章
                  </Label>
                  <textarea
                    id='pf-form-wiz-draft'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    rows={4}
                    value={draftText}
                    onChange={(e) => setDraftText(e.target.value)}
                    placeholder={
                      navigation
                        ? '例: 転入か転居か、世帯主かどうかを聞く'
                        : '例: 子ども医療費助成の申請。申請者・住所・振込先が必要'
                    }
                  />
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    生成した欄は編集画面で直せます。
                  </p>
                </div>
              ) : null}
            </div>
          )}

          {shownError ? (
            <p className='mt-4 text-dns-16N-130 text-error-1' role='alert'>
              {shownError}
            </p>
          ) : null}

          <div className='mt-6 flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={step === 'basics' || busy}
              onClick={() => {
                setLocalError(null);
                setStep('basics');
              }}
            >
              戻る
            </Button>
            {step === 'basics' ? (
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={!title.trim()}
                onClick={() => {
                  setLocalError(null);
                  if (!title.trim()) {
                    setLocalError('名前を入力してください。');
                    return;
                  }
                  setStep('start');
                }}
              >
                次へ
              </Button>
            ) : (
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={busy || (mode === 'draft' && !draftText.trim())}
                onClick={() => void finish()}
              >
                {busy ? '作成中...' : mode === 'draft' ? '生成して編集する' : '作成して編集する'}
              </Button>
            )}
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
