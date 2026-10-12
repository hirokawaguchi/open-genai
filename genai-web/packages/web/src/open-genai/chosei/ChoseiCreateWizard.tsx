import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { newId } from '@/utils/uuid';
import { toLocalInputValue } from './format';
import type { ChoseiDateInput, ChoseiEventDetail } from './types';
import { useChoseiActions, useChoseiAssist } from './useChosei';

type DateRow = { id: string; start: string; end: string; allDay: boolean };
type StepId = 'basics' | 'access' | 'dates';

const STEPS: { id: StepId; label: string; hint: string }[] = [
  {
    id: 'basics',
    label: '基本情報',
    hint: 'イベントの名前と、参加者に見せる説明です。',
  },
  {
    id: 'access',
    label: '作成者',
    hint: 'どちらも空欄で進めます。暗証番号を付けると、作成者以外が編集・削除するときに使います。',
  },
  {
    id: 'dates',
    label: '日程',
    hint: '手入力するか、自然文から候補を作れます。作成前に開始日時を確認してください。',
  },
];

const inputClass = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';

const newRow = (): DateRow => ({
  id: newId(),
  start: '',
  end: '',
  allDay: false,
});

const toDates = (rows: DateRow[]): ChoseiDateInput[] =>
  rows
    .filter((d) => d.start)
    .map((d) => ({
      start_time: new Date(d.start).toISOString(),
      end_time: d.end && !d.allDay ? new Date(d.end).toISOString() : null,
      is_all_day: d.allDay,
    }));

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (detail: ChoseiEventDetail) => void;
};

export const ChoseiCreateWizard = ({ open, onClose, onCreated }: Props) => {
  const { create, submitting, error, setError } = useChoseiActions();
  const { parseDates, busy: assistBusy, error: assistError, setError: setAssistError } =
    useChoseiAssist();
  const [step, setStep] = useState<StepId>('basics');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [creatorName, setCreatorName] = useState('');
  const [eventPassword, setEventPassword] = useState('');
  const [dates, setDates] = useState<DateRow[]>([newRow()]);
  const [nlText, setNlText] = useState('');
  const [nlNotes, setNlNotes] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep('basics');
    setTitle('');
    setDescription('');
    setCreatorName('');
    setEventPassword('');
    setDates([newRow()]);
    setNlText('');
    setNlNotes(null);
    setLocalError(null);
    setError(null);
    setAssistError(null);
  }, [open, setError, setAssistError]);

  const stepIndex = STEPS.findIndex((s) => s.id === step);
  const current = STEPS[stepIndex] ?? STEPS[0];
  const busy = submitting || assistBusy;
  const shownError = localError || error || assistError;

  const close = () => {
    if (busy) return;
    onClose();
  };

  const goBasics = () => {
    setLocalError(null);
    if (!title.trim()) {
      setLocalError('タイトルを入力してください。');
      return;
    }
    setStep('access');
  };

  const goDates = () => {
    setLocalError(null);
    const pin = eventPassword.trim();
    if (pin && !/^\d{4}$/.test(pin)) {
      setLocalError('暗証番号は4桁の数字にしてください。空欄でも進めます。');
      return;
    }
    setStep('dates');
  };

  const finish = async () => {
    if (busy) return;
    setLocalError(null);
    setError(null);
    const name = title.trim();
    const normalized = toDates(dates);
    if (!name) {
      setLocalError('タイトルを入力してください。');
      setStep('basics');
      return;
    }
    if (normalized.length === 0) {
      setLocalError('日程候補の開始日時を1件以上入力してください。');
      return;
    }
    const detail = await create({
      title: name,
      description: description.trim() || undefined,
      creator_name: creatorName.trim() || undefined,
      event_password: eventPassword.trim() || undefined,
      dates: normalized,
    });
    if (detail) onCreated(detail);
  };

  const updateRow = (id: string, patch: Partial<DateRow>) => {
    setDates((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  return (
    <CustomDialog isOpen={open} onClose={close} position='top'>
      <CustomDialogPanel className='max-w-3xl'>
        <CustomDialogHeader hasClose={true} onClose={close}>
          新しいイベント
        </CustomDialogHeader>
        <CustomDialogBody>
          <ol className='flex gap-1' aria-label='作成手順'>
            {STEPS.map((item, index) => (
              <li key={item.id} className='min-w-0 flex-1'>
                <div
                  className={`h-1 rounded-full ${index <= stepIndex ? 'bg-blue-900' : 'bg-solid-gray-200'}`}
                />
                <p
                  className={`mt-1 truncate text-dns-14N-130 ${
                    index === stepIndex ? 'text-blue-900' : 'text-solid-gray-600'
                  }`}
                  aria-current={index === stepIndex ? 'step' : undefined}
                >
                  {index + 1}. {item.label}
                </p>
              </li>
            ))}
          </ol>
          <p className='mt-3 text-dns-16N-130 text-solid-gray-600'>
            手順 {stepIndex + 1} / {STEPS.length}　{current.label}
          </p>
          <p className='mt-1 text-std-16N-170 text-solid-gray-700'>{current.hint}</p>

          {step === 'basics' && (
            <div className='mt-4 flex flex-col gap-4'>
              <div>
                <Label htmlFor='chosei-wiz-title' size='sm'>
                  タイトル
                </Label>
                <input
                  id='chosei-wiz-title'
                  className={inputClass}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder='例: 庁内打ち合わせ'
                  required
                />
              </div>
              <div>
                <Label htmlFor='chosei-wiz-desc' size='sm'>
                  説明（任意）
                </Label>
                <textarea
                  id='chosei-wiz-desc'
                  className={inputClass}
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder='例: 来月の定例会の候補日です'
                />
              </div>
            </div>
          )}

          {step === 'access' && (
            <div className='mt-4 grid gap-4 md:grid-cols-2'>
              <div>
                <Label htmlFor='chosei-wiz-creator' size='sm'>
                  作成者名（任意）
                </Label>
                <input
                  id='chosei-wiz-creator'
                  className={inputClass}
                  value={creatorName}
                  onChange={(e) => setCreatorName(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor='chosei-wiz-pin' size='sm'>
                  イベント暗証番号（4桁・任意）
                </Label>
                <input
                  id='chosei-wiz-pin'
                  className={inputClass}
                  inputMode='numeric'
                  maxLength={4}
                  value={eventPassword}
                  onChange={(e) => setEventPassword(e.target.value.replace(/\D/g, '').slice(0, 4))}
                  placeholder='作成者以外が編集するときに使用'
                />
              </div>
            </div>
          )}

          {step === 'dates' && (
            <div className='mt-4 flex flex-col gap-4'>
              <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                <Label htmlFor='chosei-wiz-nl' size='sm'>
                  自然文から日程候補を作成（LLM）
                </Label>
                <textarea
                  id='chosei-wiz-nl'
                  className='w-full rounded-4 border border-solid-gray-420 bg-white px-3 py-2 text-std-16N-170'
                  rows={2}
                  value={nlText}
                  onChange={(e) => setNlText(e.target.value)}
                  placeholder='例: 来週の火・水・木の午後2時から1時間ずつ'
                />
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  生成後に下の候補を確認・編集できます。
                </p>
                {nlNotes && !assistError && (
                  <p className='text-dns-14N-130 text-solid-gray-700'>{nlNotes}</p>
                )}
                <div>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={assistBusy || !nlText.trim()}
                    onClick={async () => {
                      if (assistBusy || !nlText.trim()) return;
                      setAssistError(null);
                      setNlNotes(null);
                      setLocalError(null);
                      const res = await parseDates(nlText.trim());
                      if (!res) return;
                      if (!res.dates.length) {
                        setNlNotes(res.notes || '候補を抽出できませんでした。');
                        return;
                      }
                      setDates(
                        res.dates.map((d) => ({
                          id: newId(),
                          start: toLocalInputValue(d.start_time, !!d.is_all_day),
                          end:
                            d.end_time && !d.is_all_day ? toLocalInputValue(d.end_time, false) : '',
                          allDay: !!d.is_all_day,
                        })),
                      );
                      setNlNotes(res.notes || `${res.dates.length}件の候補を反映しました。`);
                    }}
                  >
                    {assistBusy ? '解釈中...' : '日程候補に反映'}
                  </Button>
                </div>
              </div>

              <div className='flex flex-col gap-3'>
                <Label size='sm'>日程候補</Label>
                {dates.map((d, idx) => (
                  <div
                    key={d.id}
                    className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 p-3 md:flex-row md:items-end'
                  >
                    <div className='flex-1'>
                      <Label htmlFor={`chosei-wiz-start-${d.id}`} size='sm'>
                        開始
                      </Label>
                      <input
                        id={`chosei-wiz-start-${d.id}`}
                        type={d.allDay ? 'date' : 'datetime-local'}
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={d.start}
                        onChange={(e) => updateRow(d.id, { start: e.target.value })}
                      />
                    </div>
                    {!d.allDay && (
                      <div className='flex-1'>
                        <Label htmlFor={`chosei-wiz-end-${d.id}`} size='sm'>
                          終了（任意）
                        </Label>
                        <input
                          id={`chosei-wiz-end-${d.id}`}
                          type='datetime-local'
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          value={d.end}
                          onChange={(e) => updateRow(d.id, { end: e.target.value })}
                        />
                      </div>
                    )}
                    <label className='flex items-center gap-2 text-std-14N-160'>
                      <input
                        type='checkbox'
                        checked={d.allDay}
                        onChange={(e) => updateRow(d.id, { allDay: e.target.checked })}
                      />
                      終日
                    </label>
                    {dates.length > 1 && (
                      <Button
                        type='button'
                        variant='text'
                        size='sm'
                        onClick={() => setDates((prev) => prev.filter((x) => x.id !== d.id))}
                      >
                        削除
                      </Button>
                    )}
                    <span className='sr-only'>候補 {idx + 1}</span>
                  </div>
                ))}
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => setDates((prev) => [...prev, newRow()])}
                >
                  日程を追加
                </Button>
              </div>
            </div>
          )}

          {shownError && (
            <p className='mt-4 text-dns-16N-130 text-error-1' role='alert'>
              {shownError}
            </p>
          )}

          <div className='mt-6 flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={step === 'basics' || busy}
              onClick={() => {
                if (step === 'basics' || busy) return;
                setLocalError(null);
                setStep(step === 'dates' ? 'access' : 'basics');
              }}
            >
              戻る
            </Button>
            {step === 'basics' && (
              <Button type='button' variant='solid-fill' size='md' onClick={goBasics}>
                次へ
              </Button>
            )}
            {step === 'access' && (
              <Button type='button' variant='solid-fill' size='md' onClick={goDates}>
                次へ
              </Button>
            )}
            {step === 'dates' && (
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={busy || toDates(dates).length === 0}
                onClick={() => void finish()}
              >
                {submitting ? '作成中...' : '日程調整を作成'}
              </Button>
            )}
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
