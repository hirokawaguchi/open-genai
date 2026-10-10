import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import type {
  FormalCheck,
  FormSummary,
  ProcedureChoiceField,
  ProcedureReview,
  ProcedureRule,
  ReviewLine,
  SlotReview,
} from './types';

const FALLBACK_CHECKS: FormalCheck[] = [
  { id: 'file_present', label: 'ファイルがある' },
  { id: 'pdf_or_image', label: 'PDF または画像' },
  { id: 'issued_within_3_months', label: '発行日から3か月以内' },
];

const ruleKey = (componentId: string, option: string) => `${componentId}\t${option}`;

const newLine = (text: string): ReviewLine => ({
  id: crypto.randomUUID().replace(/-/g, '').slice(0, 8),
  text,
});

const emptyRule = (componentId: string, option: string): ProcedureRule => ({
  component_id: componentId,
  option,
  form_ids: [],
  notes: '',
  prepare: [],
  refs: [],
  reviews: [],
  cross: [],
});

type Card = {
  slotId: string;
  title: string;
  kind: 'yoshiki' | 'attach';
  formId?: string;
  unpublished?: boolean;
};

const reviewOf = (rule: ProcedureRule, slotId: string): SlotReview =>
  (rule.reviews || []).find((r) => r.slot_id === slotId) || {
    slot_id: slotId,
    formal: [],
    content: [],
  };

export const ProcedureSlotEditor = ({
  fields,
  styleForms,
  guideFormId,
  guideTitle,
  singleForm,
  ruleMap,
  review,
  formalChecks,
  canEdit,
  onRule,
  onReview,
}: {
  fields: ProcedureChoiceField[];
  styleForms: FormSummary[];
  guideFormId: string;
  guideTitle: string;
  singleForm: boolean;
  ruleMap: Map<string, ProcedureRule>;
  review: ProcedureReview;
  formalChecks?: FormalCheck[];
  canEdit: boolean;
  onRule: (componentId: string, option: string, patch: Partial<ProcedureRule>) => void;
  onReview: (next: ProcedureReview) => void;
}) => {
  const checks = formalChecks?.length ? formalChecks : FALLBACK_CHECKS;
  const answers = fields.flatMap((field) => {
    const items = field.option_items?.length
      ? field.option_items
      : field.options.map((option) => ({ value: option, label: option }));
    return items.map((item) => ({
      componentId: field.id,
      question: field.label,
      option: item.value,
      label: item.label,
    }));
  });
  const answerKey = answers.map((a) => ruleKey(a.componentId, a.option)).join('|');
  const [selected, setSelected] = useState('');
  const [addFormId, setAddFormId] = useState('');
  const [attachName, setAttachName] = useState('');
  const [contentDraft, setContentDraft] = useState<Record<string, string>>({});
  const [crossDraft, setCrossDraft] = useState('');

  useEffect(() => {
    if (singleForm) return;
    const keys = answerKey.split('|').filter(Boolean);
    if (keys.includes(selected)) return;
    setSelected(keys[0] || '');
  }, [answerKey, selected, singleForm]);

  const patchSlot = (
    current: SlotReview[],
    slotId: string,
    patch: Partial<SlotReview>,
  ): SlotReview[] => {
    const reviews = current.map((r) => ({ ...r, formal: [...r.formal], content: [...r.content] }));
    const index = reviews.findIndex((r) => r.slot_id === slotId);
    const base = index >= 0 ? reviews[index] : { slot_id: slotId, formal: [], content: [] };
    const next = { ...base, ...patch, slot_id: slotId };
    if (index >= 0) reviews[index] = next;
    else reviews.push(next);
    return reviews;
  };

  const renderCard = (
    card: Card,
    slot: SlotReview,
    onChange: (patch: Partial<SlotReview>) => void,
    onRemove?: () => void,
  ) => (
    <article key={card.slotId} className='rounded-8 border border-solid-gray-300 bg-white p-4'>
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div>
          <h3 className='text-std-16B-150'>
            {card.title}
            {card.unpublished ? (
              <span className='ml-2 rounded-4 bg-orange-50 px-1.5 py-0.5 text-dns-14N-130 text-orange-800'>
                未公開
              </span>
            ) : null}
          </h3>
          <p className='text-dns-14N-130 text-solid-gray-600'>
            {card.kind === 'attach' ? '添付' : '様式'}
          </p>
        </div>
        <div className='flex flex-wrap gap-2'>
          {card.formId ? (
            <Link to={`/patchform/${card.formId}/edit`} className='inline-flex'>
              <Button type='button' variant='outline' size='sm'>
                用紙を編集
              </Button>
            </Link>
          ) : null}
          {onRemove ? (
            <Button type='button' variant='outline' size='sm' disabled={!canEdit} onClick={onRemove}>
              外す
            </Button>
          ) : null}
        </div>
      </div>
      <fieldset className='mt-3' disabled={!canEdit}>
        <legend className='text-dns-14N-130 text-solid-gray-700'>形式</legend>
        <div className='mt-1 flex flex-col gap-1'>
          {checks.map((check) => {
            const checked = slot.formal.includes(check.id);
            return (
              <label key={check.id} className='flex items-center gap-2 text-std-16N-170'>
                <input
                  type='checkbox'
                  checked={checked}
                  onChange={(e) => {
                    const formal = e.target.checked
                      ? [...slot.formal, check.id]
                      : slot.formal.filter((id) => id !== check.id);
                    onChange({ formal });
                  }}
                />
                <span>{check.label}</span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className='mt-3'>
        <p className='text-dns-14N-130 text-solid-gray-700'>内容の確認</p>
        <ul className='mt-1 flex flex-col gap-1'>
          {slot.content.map((line) => (
            <li key={line.id} className='flex items-center gap-2'>
              <span className='min-w-0 flex-1 text-std-16N-170'>{line.text}</span>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={!canEdit}
                onClick={() => onChange({ content: slot.content.filter((c) => c.id !== line.id) })}
              >
                削除
              </Button>
            </li>
          ))}
        </ul>
        <div className='mt-2 flex flex-wrap gap-2'>
          <input
            className='min-w-[12rem] flex-1 rounded-4 border border-solid-gray-420 px-3 py-2'
            value={contentDraft[card.slotId] || ''}
            disabled={!canEdit}
            placeholder='例: 勤務先名が読める'
            onChange={(e) => setContentDraft((prev) => ({ ...prev, [card.slotId]: e.target.value }))}
          />
          <Button
            type='button'
            variant='outline'
            size='sm'
            disabled={!canEdit}
            onClick={() => {
              const text = (contentDraft[card.slotId] || '').trim();
              if (!text) return;
              onChange({ content: [...slot.content, newLine(text)] });
              setContentDraft((prev) => ({ ...prev, [card.slotId]: '' }));
            }}
          >
            確認を足す
          </Button>
        </div>
      </div>
    </article>
  );

  if (singleForm) {
    const slotId = guideFormId ? `yoshiki:${guideFormId}` : '';
    const slot = review.slots.find((s) => s.slot_id === slotId) || {
      slot_id: slotId,
      formal: [],
      content: [],
    };
    return (
      <section className='flex flex-col gap-3'>
        <h2 className='text-std-18B-160'>この用紙の審査</h2>
        <p className='text-std-16N-170 text-solid-gray-700'>
          申請者に出す書類はこの1枚です。受付が見る基準をここに書きます。
        </p>
        {slotId
          ? renderCard(
              { slotId, title: guideTitle || '申請用紙', kind: 'yoshiki', formId: guideFormId },
              slot,
              (patch) => onReview({ ...review, slots: patchSlot(review.slots, slotId, patch) }),
            )
          : null}
      </section>
    );
  }

  const current = answers.find((a) => ruleKey(a.componentId, a.option) === selected);
  const rule = current
    ? ruleMap.get(ruleKey(current.componentId, current.option)) ||
      emptyRule(current.componentId, current.option)
    : null;
  const cards: Card[] = [];
  if (rule && current) {
    for (const id of rule.form_ids) {
      const form = styleForms.find((f) => f.id === id);
      cards.push({
        slotId: `yoshiki:${id}`,
        title: form?.title || '申請用紙',
        kind: 'yoshiki',
        formId: id,
        unpublished: Boolean(form && !form.has_opening),
      });
    }
    for (const name of rule.prepare || []) {
      cards.push({ slotId: `attach:${name}`, title: name, kind: 'attach' });
    }
  }
  const remaining = styleForms.filter((f) => !rule?.form_ids.includes(f.id));

  return (
    <section id='pf-mapping' className='flex flex-col gap-4'>
      <h2 className='text-std-18B-160'>答えごとの書類と審査</h2>
      <p className='text-std-16N-170 text-solid-gray-700'>
        左の答えを選ぶと、そのとき出す書類が右に並びます。書類を足し、受付が見る基準をカードに書きます。
      </p>
      {answers.length === 0 ? (
        <p className='text-solid-gray-700'>
          案内にラジオやプルダウンがありません。
          {guideFormId ? (
            <>
              {' '}
              <Link to={`/patchform/${guideFormId}/edit`} className='text-blue-900 underline-offset-2 hover:underline'>
                質問に選択肢を足す
              </Link>
            </>
          ) : null}
        </p>
      ) : (
        <div className='grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]'>
          <div className='flex flex-col gap-2' role='tablist' aria-label='案内の答え'>
            {answers.map((answer) => {
              const key = ruleKey(answer.componentId, answer.option);
              const active = key === selected;
              return (
                <button
                  key={key}
                  type='button'
                  role='tab'
                  aria-selected={active}
                  onClick={() => setSelected(key)}
                  className={`rounded-8 border px-3 py-2 text-left ${
                    active
                      ? 'border-blue-900 bg-blue-50 text-blue-900'
                      : 'border-solid-gray-300 bg-white text-solid-gray-800'
                  }`}
                >
                  <span className='block text-dns-14N-130 text-solid-gray-600'>{answer.question}</span>
                  <span className='block text-std-16B-150'>{answer.label}</span>
                </button>
              );
            })}
          </div>
          {rule && current ? (
            <div className='flex flex-col gap-3'>
              <p className='text-std-16B-150'>
                「{current.label}」のときに出す書類
              </p>
              {cards.length === 0 ? (
                <p className='text-std-16N-170 text-solid-gray-700'>まだ書類がありません。</p>
              ) : (
                cards.map((card) =>
                  renderCard(
                    card,
                    reviewOf(rule, card.slotId),
                    (patch) =>
                      onRule(current.componentId, current.option, {
                        reviews: patchSlot(rule.reviews || [], card.slotId, patch),
                      }),
                    () => {
                      if (card.kind === 'yoshiki' && card.formId) {
                        onRule(current.componentId, current.option, {
                          form_ids: rule.form_ids.filter((id) => id !== card.formId),
                          reviews: (rule.reviews || []).filter((r) => r.slot_id !== card.slotId),
                        });
                      } else {
                        onRule(current.componentId, current.option, {
                          prepare: (rule.prepare || []).filter((name) => `attach:${name}` !== card.slotId),
                          reviews: (rule.reviews || []).filter((r) => r.slot_id !== card.slotId),
                        });
                      }
                    },
                  ),
                )
              )}
              <div className='flex flex-wrap items-end gap-2'>
                <div className='min-w-[12rem] flex-1'>
                  <Label htmlFor='pf-add-form' size='sm'>
                    様式を足す
                  </Label>
                  <select
                    id='pf-add-form'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={addFormId}
                    disabled={!canEdit}
                    onChange={(e) => setAddFormId(e.target.value)}
                  >
                    <option value=''>用紙を選ぶ</option>
                    {remaining.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.title}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={!canEdit || !addFormId}
                  onClick={() => {
                    onRule(current.componentId, current.option, {
                      form_ids: [...rule.form_ids, addFormId],
                    });
                    setAddFormId('');
                  }}
                >
                  足す
                </Button>
              </div>
              <div className='flex flex-wrap items-end gap-2'>
                <div className='min-w-[12rem] flex-1'>
                  <Label htmlFor='pf-add-attach' size='sm'>
                    添付を足す
                  </Label>
                  <input
                    id='pf-add-attach'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={attachName}
                    disabled={!canEdit}
                    placeholder='例: 勤務証明書'
                    onChange={(e) => setAttachName(e.target.value)}
                  />
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={!canEdit || !attachName.trim()}
                  onClick={() => {
                    const name = attachName.trim();
                    if ((rule.prepare || []).includes(name)) {
                      setAttachName('');
                      return;
                    }
                    onRule(current.componentId, current.option, {
                      prepare: [...(rule.prepare || []), name],
                    });
                    setAttachName('');
                  }}
                >
                  足す
                </Button>
              </div>
              <div>
                <Label htmlFor={`note-${current.componentId}-${current.option}`} size='sm'>
                  解説
                </Label>
                <textarea
                  id={`note-${current.componentId}-${current.option}`}
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  rows={2}
                  value={rule.notes || ''}
                  disabled={!canEdit}
                  onChange={(e) => onRule(current.componentId, current.option, { notes: e.target.value })}
                />
              </div>
              <div>
                <p className='text-dns-14N-130 text-solid-gray-700'>枠をまたぐ確認</p>
                <ul className='mt-1 flex flex-col gap-1'>
                  {(rule.cross || []).map((line) => (
                    <li key={line.id} className='flex items-center gap-2'>
                      <span className='min-w-0 flex-1 text-std-16N-170'>{line.text}</span>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        disabled={!canEdit}
                        onClick={() =>
                          onRule(current.componentId, current.option, {
                            cross: (rule.cross || []).filter((c) => c.id !== line.id),
                          })
                        }
                      >
                        削除
                      </Button>
                    </li>
                  ))}
                </ul>
                <div className='mt-2 flex flex-wrap gap-2'>
                  <input
                    className='min-w-[12rem] flex-1 rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={crossDraft}
                    disabled={!canEdit}
                    placeholder='例: 申込書と証明書の氏名が同じ'
                    onChange={(e) => setCrossDraft(e.target.value)}
                  />
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    disabled={!canEdit}
                    onClick={() => {
                      const text = crossDraft.trim();
                      if (!text) return;
                      onRule(current.componentId, current.option, {
                        cross: [...(rule.cross || []), newLine(text)],
                      });
                      setCrossDraft('');
                    }}
                  >
                    確認を足す
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
};
