import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  PiEyeBold,
  PiFileTextBold,
  PiNotePencilBold,
  PiPaperclipBold,
  PiSignpostBold,
} from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { PatchformSubnav } from './PatchformSubnav';
import { FillForm } from './runtime/FillForm';
import {
  type FormSummary,
  omitsNavigation,
  type ProcedureResolvePreview,
  type ProcedureRule,
  type SlotKind,
  type SlotTemplate,
} from './types';
import {
  downloadFormTemplate,
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  resolveProcedurePreview,
  usePatchformConfig,
  usePatchformDetail,
  usePatchformList,
  usePatchformProcedure,
  usePatchformProcedureActions,
  usePatchformProcedureCatalog,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
};

const requiredLabel: Record<string, string> = {
  required: '必須',
  recommended: '推奨',
  optional: '任意',
};

const previewKindIcon = (kind: SlotKind) => {
  if (kind === 'attach') return <PiPaperclipBold className='size-4 text-solid-gray-600' />;
  if (kind === 'data') return <PiSignpostBold className='size-4 text-blue-900' />;
  return <PiFileTextBold className='size-4 text-solid-gray-600' />;
};

const ruleKey = (componentId: string, option: string) => `${componentId}\t${option}`;

const rulesToMap = (rules: ProcedureRule[]) => {
  const out = new Map<string, ProcedureRule>();
  for (const rule of rules) {
    out.set(ruleKey(rule.component_id, rule.option), { ...rule, form_ids: [...rule.form_ids] });
  }
  return out;
};

export const PatchformProcedureEditPage = () => {
  const { procedureId } = useParams();
  const navigate = useNavigate();
  const { procedure, isLoading, loadError, mutate } = usePatchformProcedure(procedureId);
  const { forms } = usePatchformList();
  const { config } = usePatchformConfig();
  const { save, setStatus, setProcedureVisibility, remove, submitting, error, setError } =
    usePatchformProcedureActions();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [guideFormId, setGuideFormId] = useState('');
  const [notifyEmails, setNotifyEmails] = useState('');
  const [ruleMap, setRuleMap] = useState<Map<string, ProcedureRule>>(new Map());
  const [pane, setPane] = useState<'edit' | 'preview'>('edit');
  const [previewValues, setPreviewValues] = useState<Record<string, unknown>>({});
  const { form: guidePreviewForm, isLoading: guideLoading } = usePatchformDetail(
    pane === 'preview' ? guideFormId || undefined : undefined,
  );
  const guideDefinition = guidePreviewForm?.fill_definition ?? guidePreviewForm?.definition;
  const { slots: previewSlots } = usePatchformProcedureCatalog(
    pane === 'preview' ? procedureId : undefined,
  );
  const [resolvePreview, setResolvePreview] = useState<ProcedureResolvePreview | null>(null);
  const [resolveBusy, setResolveBusy] = useState(false);
  const [resolveUnavailable, setResolveUnavailable] = useState(false);
  const previewJson = JSON.stringify(previewValues);
  useEffect(() => {
    if (pane !== 'preview' || !procedureId || !guideDefinition) return;
    let alive = true;
    setResolveBusy(true);
    const timer = setTimeout(async () => {
      const res = await resolveProcedurePreview(procedureId, JSON.parse(previewJson));
      if (!alive) return;
      setResolvePreview(res);
      setResolveUnavailable(res === null);
      setResolveBusy(false);
    }, 300);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [pane, procedureId, guideDefinition, previewJson]);

  useEffect(() => {
    if (!procedure) return;
    setName(procedure.name);
    setDescription(procedure.description || '');
    setGuideFormId(procedure.guide_form_id);
    setNotifyEmails((procedure.notify_emails || []).join('\n'));
    setRuleMap(rulesToMap(procedure.mapping?.rules || []));
  }, [procedure]);

  const styleForms = useMemo(
    () => forms.filter((f) => f.id !== guideFormId),
    [forms, guideFormId],
  );

  const updateRule = (componentId: string, option: string, patch: Partial<ProcedureRule>) => {
    setRuleMap((prev) => {
      const next = new Map(prev);
      const key = ruleKey(componentId, option);
      const current = next.get(key) || {
        component_id: componentId,
        option,
        form_ids: [],
        notes: '',
        prepare: [],
        refs: [],
      };
      next.set(key, { ...current, ...patch, component_id: componentId, option });
      return next;
    });
  };

  const collectedRules = (): ProcedureRule[] => {
    const out: ProcedureRule[] = [];
    for (const rule of ruleMap.values()) {
      if (!rule.form_ids.length && !rule.notes && !(rule.prepare || []).length && !(rule.refs || []).length) {
        continue;
      }
      out.push({
        component_id: rule.component_id,
        option: rule.option,
        form_ids: rule.form_ids,
        notes: rule.notes || '',
        prepare: rule.prepare || [],
        refs: rule.refs || [],
      });
    }
    return out;
  };

  const onSave = async () => {
    if (!procedureId) return;
    setError(null);
    const saved = await save(procedureId, {
      name: name.trim(),
      description: description.trim(),
      guide_form_id: guideFormId,
      mapping: { rules: collectedRules() },
      notify_emails: notifyEmails
        .split(/[\n,、;]+/)
        .map((addr) => addr.trim())
        .filter(Boolean),
    });
    if (saved) await mutate();
  };

  const fields = procedure?.choice_fields || [];
  const singleForm = Boolean(procedure && omitsNavigation(procedure));
  const templateEntries: {
    key: string;
    title: string;
    formId: string;
    template: SlotTemplate;
  }[] = [];
  if (singleForm && guideFormId && guidePreviewForm?.template) {
    templateEntries.push({
      key: 'self',
      title: guidePreviewForm.title || name,
      formId: guideFormId,
      template: guidePreviewForm.template,
    });
  }
  for (const s of previewSlots) {
    if (s.template && s.form_id) {
      templateEntries.push({
        key: s.slot_id,
        title: s.title,
        formId: s.form_id,
        template: s.template,
      });
    }
  }
  const catalogSlotById = new Map(previewSlots.map((s) => [s.slot_id, s] as const));
  const formById = new Map(forms.map((f) => [f.id, f] as const));
  const answerValues = (v: unknown): string[] =>
    Array.isArray(v)
      ? v.map((x) => String(x))
      : v === null || v === undefined || v === ''
        ? []
        : [String(v)];
  const matchedFormIds = new Set<string>();
  for (const r of procedure?.mapping?.rules ?? []) {
    if (answerValues(previewValues[r.component_id]).includes(r.option)) {
      for (const fid of r.form_ids) matchedFormIds.add(fid);
    }
  }
  const unpublishedMapped: FormSummary[] = [];
  for (const id of matchedFormIds) {
    const f = formById.get(id);
    if (f && !f.has_opening) unpublishedMapped.push(f);
  }
  const nameLooksDraft = /[#＃]|目次/.test(name);
  const needsCopyReview = description.includes('【確認】') || nameLooksDraft;
  const hasMappedForms = collectedRules().some((r) => r.form_ids.length > 0);
  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const knownKeys = new Set(
    fields.flatMap((f) => f.options.map((option) => ruleKey(f.id, option))),
  );
  const orphanRules = [...ruleMap.values()].filter(
    (rule) => !knownKeys.has(ruleKey(rule.component_id, rule.option)),
  );

  return (
    <LayoutBody>
      <PageTitle title={procedure?.name || '手続き'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '手続き', to: '/patchform/procedures' },
            { label: procedure?.name || '編集' },
          ]}
        />
        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}
        {procedure && (
          <>
            <div className='flex flex-col gap-2'>
              <h1 className='text-std-20B-160 lg:text-std-24B-150'>{procedure.name}</h1>
              <PatchformSubnav current='procedures' />
              <p className='text-std-16N-170 text-solid-gray-700'>
                {statusLabel[procedure.status] || procedure.status}
                {singleForm
                  ? '。申請用紙はこの1枚です。'
                  : needsCopyReview
                    ? '。手引きから作った直後は下書きです。名前と対応を直してから、下の「保存する」「公開する」を使います。'
                    : '。各答えのときに出す申請用紙を選んでから、保存または公開します。'}
              </p>
            </div>

            <div
              className='flex flex-wrap gap-2 border-b border-solid-gray-300'
              role='tablist'
              aria-label='編集とプレビュー'
            >
              {(
                [
                  { id: 'edit', label: '編集', icon: PiNotePencilBold },
                  { id: 'preview', label: 'プレビュー', icon: PiEyeBold },
                ] as const
              ).map((t) => {
                const Icon = t.icon;
                return (
                  <button
                    key={t.id}
                    type='button'
                    role='tab'
                    aria-selected={pane === t.id}
                    onClick={() => setPane(t.id)}
                    className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-oln-16B-100 ${
                      pane === t.id
                        ? 'border-blue-900 text-blue-900'
                        : 'border-transparent text-solid-gray-600 hover:text-solid-gray-900'
                    }`}
                  >
                    <Icon aria-hidden={true} className='size-5' />
                    {t.label}
                  </button>
                );
              })}
            </div>

            {pane === 'edit' && (
            <>
            {!singleForm ? (
            <PatchformProcedureCoach
              title='操作の流れ'
              defaultOpen={needsCopyReview}
              lead={
                singleForm
                  ? '申請用紙はこの1枚です。保存して公開すると受付が始まります。'
                  : 'チェックを付けた申請用紙だけが、申請者や回答者に出ます。'
              }
              note={
                <div className='flex flex-col gap-1'>
                  <p className='text-std-16B-150'>ナビゲーションフォームとは</p>
                  <p className='text-dns-16N-130 text-solid-gray-700'>
                    申請者・回答者が最初に答える「案内」の1枚です。ラジオボタンやプルダウンの答えに応じて、必要な申請用紙を出し分けます（出し分けは下の「答えと申請用紙の対応」で設定します）。
                  </p>
                  <p className='text-dns-16N-130 text-solid-gray-700'>
                    答えによって必要書類が変わる手続きに向いています。選択肢が無く自由記入だけのときはナビゲーションにならず、その1枚だけを配る「単一フォーム」として公開されます。1枚で完結する手続きは単一フォームのままで構いません。
                  </p>
                </div>
              }
              steps={[
                {
                  id: 'review',
                  label: '名前と説明を直す',
                  done: !needsCopyReview,
                  hint: '庁内の一覧で使う短い名前にします。説明の【確認】は読んで直すか消します。',
                  action: { label: '名前の欄へ', onClick: () => scrollTo('pf-pe-name') },
                },
                {
                  id: 'choices',
                  label: singleForm ? '申請用紙を確認する' : '質問にラジオやプルダウンがある',
                  done: singleForm || fields.length > 0,
                  hint: singleForm
                    ? 'この手続きはナビゲーションフォームを使いません。用紙を直すときは申請用紙を編集してください。'
                    : '答えの選択肢が無いと、申請用紙を振り分けられません。無ければナビゲーションフォームを編集してください。',
                  action: procedure.guide_form_id
                    ? {
                        label: singleForm ? '申請用紙を編集する' : 'ナビゲーションフォームを編集する',
                        to: `/patchform/${procedure.guide_form_id}/edit`,
                      }
                    : undefined,
                },
                ...(singleForm
                  ? []
                  : [
                      {
                        id: 'map',
                        label: '答えごとに申請用紙を選ぶ',
                        done: hasMappedForms,
                        hint: '例: 「転入」なら転入届。「該当しない」なら用紙を付けない、など。',
                        action: {
                          label: '対応の欄へ',
                          onClick: () => scrollTo('pf-mapping'),
                        },
                      },
                    ]),
                {
                  id: 'publish',
                  label: '保存して公開する',
                  done: procedure.status === 'published',
                  hint: '公開すると、申請者や回答者が使える受付が始まります。確認が残っているときは、先に直してください。',
                  action: procedure.can_edit
                    ? {
                        label: '保存・公開のボタンへ',
                        onClick: () => scrollTo('pf-proc-actions'),
                      }
                    : undefined,
                },
                {
                  id: 'inbox',
                  label: '届いた申請は申請受付で見る',
                  done: false,
                  hint: singleForm
                    ? '申請用紙を提出すると束ができます。進捗の確認は申請受付です。'
                    : '案内を提出すると束ができます。進捗の確認は申請受付です。',
                  action: {
                    label: '申請受付を開く',
                    to: `/patchform/inbox/${encodeURIComponent(procedure.id)}`,
                  },
                },
              ]}
            />
            ) : null}

            {(procedure.warnings || []).length > 0 && (
              <div className='rounded-8 border border-orange-400 bg-orange-50 px-4 py-3' role='status'>
                <p className='text-std-16B-150'>案内の選択肢が対応表と一致しません</p>
                <ul className='mt-2 list-disc pl-5 text-std-16N-170'>
                  {procedure.warnings?.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {description.includes('【確認】') && (
              <div className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3' role='status'>
                <p className='text-std-16B-150'>第1版の確認事項があります</p>
                <p className='mt-1 text-std-16N-170 text-solid-gray-700'>
                  手引きから自動で拾ったメモです。説明欄の【確認】を読んで直すか消し、下の用紙のチェックを確認してから公開してください。
                </p>
                <div className='mt-3 flex flex-wrap gap-2'>
                  <Button type='button' variant='outline' size='sm' onClick={() => scrollTo('pf-pe-desc')}>
                    説明を見る
                  </Button>
                  <Button type='button' variant='outline' size='sm' onClick={() => scrollTo('pf-mapping')}>
                    用紙の対応を見る
                  </Button>
                </div>
              </div>
            )}

            <div className='flex flex-col gap-4'>
              <div>
                <Label htmlFor='pf-pe-name' size='sm'>
                  名前
                </Label>
                <input
                  id='pf-pe-name'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={!procedure.can_edit}
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  庁内の一覧で使う名前です。
                </p>
              </div>
              <div>
                <Label htmlFor='pf-pe-desc' size='sm'>
                  説明
                </Label>
                <textarea
                  id='pf-pe-desc'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  rows={description.includes('【確認】') ? 5 : 2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  disabled={!procedure.can_edit}
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  職員向けのメモです。空欄でも構いません。
                </p>
              </div>
              <div>
                <Label htmlFor='pf-pe-notify' size='sm'>
                  職員への通知先
                </Label>
                <textarea
                  id='pf-pe-notify'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  rows={2}
                  value={notifyEmails}
                  onChange={(e) => setNotifyEmails(e.target.value)}
                  disabled={!procedure.can_edit}
                  placeholder='staff@example.lg.jp'
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  案内が提出されたとき、職員へ知らせます。1行に1件、またはカンマ区切り。本文に回答は入れません。
                  {config?.mail?.smtp
                    ? ' 庁内のメールサーバに送ります。'
                    : config?.mail?.dump
                      ? ' いまはメールサーバの代わりに、サーバ上のテキストに書き出します。'
                      : ' いまはメールサーバ未設定のため、宛先を書いても送られません。'}
                </p>
              </div>
              <div>
                <Label htmlFor='pf-pe-vis' size='sm'>
                  公開範囲
                </Label>
                <select
                  id='pf-pe-vis'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={procedure.visibility === 'both' ? 'both' : 'internal'}
                  disabled={!procedure.can_edit}
                  onChange={async (e) => {
                    const next = await setProcedureVisibility(
                      procedure.id,
                      e.target.value === 'both' ? 'both' : 'internal',
                    );
                    if (next) await mutate();
                  }}
                >
                  <option value='internal'>庁内のみ</option>
                  <option value='both'>庁内と外部</option>
                </select>
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  庁内/庁外の公開はこの手続きで決めます。「庁内と外部」にすると、案内と申請用紙すべてが外部からも記入できます。マイナンバーなど庁内専用の部品を含む場合は庁外公開できません。
                </p>
              </div>
              <div>
                <Label htmlFor='pf-pe-guide' size='sm'>
                  {singleForm ? '申請用紙' : 'ナビゲーションフォーム'}
                </Label>
                <select
                  id='pf-pe-guide'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={guideFormId}
                  onChange={(e) => setGuideFormId(e.target.value)}
                  disabled={!procedure.can_edit}
                >
                  {[...forms]
                    .sort((a, b) => {
                      const aNav = (a.tags || []).includes(NAVIGATION_TAG) ? 0 : 1;
                      const bNav = (b.tags || []).includes(NAVIGATION_TAG) ? 0 : 1;
                      return aNav - bNav;
                    })
                    .map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.title}（{f.locked || f.work_status === 'ready' ? '作成完了' : '作成中'}
                      {f.has_opening ? ' · 受付中' : ''}
                      {(f.tags || []).length ? ` · ${(f.tags || []).join('、')}` : ''}）
                    </option>
                  ))}
                </select>
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  {singleForm
                    ? 'この1枚を公開します。ラジオやプルダウンを足すと、ナビゲーションとして使えるようになります。'
                    : '申請者や回答者が最初に答えるナビゲーションフォームです。下の対応は、このフォームの答えごとに決まります。'}
                </p>
                {procedure.guide_public_url ? (
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    {procedure.status === 'published' ? '公開 URL' : '前回の公開 URL'}:{' '}
                    {procedure.guide_public_url}
                  </p>
                ) : null}
              </div>
            </div>
            {!singleForm ? (
            <section id='pf-mapping' className='flex flex-col gap-4'>
              <h2 className='text-std-18B-160'>答えと申請用紙の対応</h2>
              <>
              <p className='text-std-16N-170 text-solid-gray-700'>
                申請者がその答えを選んだとき、手続きへ追加するフォームにチェックします。
              </p>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                「未公開」のフォームは、手続きを公開すると自動で受付が開き、申請者に出せるようになります。
              </p>
              {fields.length === 0 ? (
                <div className='rounded-8 border border-solid-gray-300 px-4 py-3'>
                  <p className='text-solid-gray-700'>
                    選んだフォームに、ラジオやプルダウンがありません。
                  </p>
                  {procedure.guide_form_id ? (
                    <p className='mt-2'>
                      <Link
                        to={`/patchform/${procedure.guide_form_id}/edit`}
                        className='text-blue-900 underline-offset-2 hover:underline'
                      >
                        質問に選択肢を足す
                      </Link>
                    </p>
                  ) : null}
                </div>
              ) : (
                fields.map((field) => (
                  <div key={field.id} className='rounded-8 border border-solid-gray-300 p-4'>
                    <h3 className='text-std-16B-150'>質問「{field.label}」</h3>
                    <div className='mt-3 flex flex-col gap-4'>
                      {(field.option_items?.length
                        ? field.option_items
                        : field.options.map((option) => ({ value: option, label: option }))
                      ).map((item) => {
                        const option = item.value;
                        const rule = ruleMap.get(ruleKey(field.id, option));
                        return (
                          <div key={option} className='border-t border-solid-gray-300 pt-3'>
                            <p className='text-std-16B-150'>
                              答えが「{item.label}」
                              {item.label !== item.value ? `（${item.value}）` : ''}
                              のとき
                            </p>
                            <fieldset className='mt-2'>
                              <legend className='text-dns-14N-130 text-solid-gray-700'>
                                このとき追加するフォーム
                              </legend>
                              <div className='mt-1 flex flex-col gap-1'>
                                {styleForms.map((f) => {
                                  const checked = Boolean(rule?.form_ids.includes(f.id));
                                  return (
                                    <label key={f.id} className='flex items-center gap-2 text-std-16N-170'>
                                      <input
                                        type='checkbox'
                                        checked={checked}
                                        disabled={!procedure.can_edit}
                                        onChange={(e) => {
                                          const current = rule?.form_ids || [];
                                          const next = e.target.checked
                                            ? [...current, f.id]
                                            : current.filter((id) => id !== f.id);
                                          updateRule(field.id, option, { form_ids: next });
                                        }}
                                      />
                                      <span>{f.title}</span>
                                      {checked && !f.has_opening ? (
                                        <span className='rounded-4 bg-orange-50 px-1.5 py-0.5 text-dns-14N-130 text-orange-800'>
                                          未公開
                                        </span>
                                      ) : null}
                                    </label>
                                  );
                                })}
                                {styleForms.length === 0 ? (
                                  <p className='text-dns-14N-130 text-solid-gray-600'>
                                    追加できるフォームがありません。先に申請フォームを作成してください。
                                  </p>
                                ) : null}
                              </div>
                            </fieldset>
                            <div className='mt-2'>
                              <Label htmlFor={`note-${field.id}-${option}`} size='sm'>
                                解説
                              </Label>
                              <textarea
                                id={`note-${field.id}-${option}`}
                                className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                                rows={2}
                                value={rule?.notes || ''}
                                disabled={!procedure.can_edit}
                                onChange={(e) => updateRule(field.id, option, { notes: e.target.value })}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
              {orphanRules.length > 0 && (
                <p className='text-solid-gray-700'>
                  案内に無い対応が {orphanRules.length} 件残っています。保存すると残ります。選択肢を戻すか、空にして消してください。
                </p>
              )}
              </>
            </section>
            ) : null}
            </>
            )}

            {pane === 'preview' && (
              <section className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                <h2 className='text-std-20B-160'>{name || procedure.name}</h2>
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  申請者が最初に見る{singleForm ? '申請フォーム' : 'ナビゲーションフォーム'}
                  のプレビューです。入力しても保存されません。
                </p>
                {guideDefinition ? (
                  <div className='mt-4'>
                    <FillForm
                      definition={guideDefinition}
                      values={previewValues}
                      onChange={(id, v) => setPreviewValues((p) => ({ ...p, [id]: v }))}
                      onExtract={extractPatchformFile}
                      onPostalLookup={lookupPatchformPostal}
                      onCorporateLookup={lookupPatchformCorporate}
                    />
                  </div>
                ) : (
                  <p className='mt-4 text-std-16N-170 text-solid-gray-700'>
                    {guideLoading
                      ? 'プレビューを読み込み中...'
                      : guideFormId
                        ? 'このフォームはプレビューを表示できませんでした。'
                        : '申請用紙が選ばれていません。編集タブで用紙を選んでください。'}
                  </p>
                )}
                {guideDefinition && !singleForm ? (
                  <div className='mt-6 border-t border-solid-gray-300 pt-4'>
                    <h3 className='flex items-center gap-2 text-std-16B-150'>
                      <PiFileTextBold aria-hidden={true} className='size-5 text-solid-gray-700' />
                      この答えのときに申請者へ出る書類
                      {!resolveUnavailable
                        ? `（${(resolvePreview?.items.length ?? 0) + unpublishedMapped.length}件）`
                        : ''}
                      {resolveBusy ? (
                        <span className='text-dns-14N-130 text-solid-gray-500'>判定中…</span>
                      ) : null}
                    </h3>
                    <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                      上の案内フォームの答えを選ぶと、その申請者に出る書類がここに並びます。答えを変えると自動で切り替わります。
                    </p>
                    {resolveUnavailable ? (
                      <div className='mt-3'>
                        <p className='rounded-8 bg-solid-gray-50 p-3 text-dns-14N-130 text-solid-gray-700'>
                          必要書類の事前確認は利用できませんでした。登録済みのひな型のみ表示します。
                        </p>
                        {templateEntries.length > 0 ? (
                          <ul className='mt-3 flex flex-col gap-2'>
                            {templateEntries.map((t) => (
                              <li
                                key={t.key}
                                className='flex flex-wrap items-center justify-between gap-2 rounded-8 border border-solid-gray-300 bg-white px-3 py-2'
                              >
                                <span className='min-w-0 flex-1'>
                                  <span className='block text-std-16N-170'>{t.title}</span>
                                  <span className='block truncate text-dns-14N-130 text-solid-gray-600'>
                                    {t.template.filename}
                                  </span>
                                </span>
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='sm'
                                  className='inline-flex shrink-0 items-center justify-center whitespace-nowrap'
                                  onClick={() => void downloadFormTemplate(t.formId, t.template)}
                                >
                                  ダウンロード
                                </Button>
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    ) : (resolvePreview && resolvePreview.items.length > 0) ||
                      unpublishedMapped.length > 0 ? (
                      <>
                        <ul className='mt-3 divide-y divide-solid-gray-200 rounded-8 border border-solid-gray-300 bg-white'>
                          {(resolvePreview?.items ?? []).map((it) => {
                            const slot = catalogSlotById.get(it.slot_id);
                            const tpl = slot?.template;
                            const fid = slot?.form_id;
                            return (
                              <li
                                key={it.slot_id || it.title}
                                className='flex flex-wrap items-center gap-3 px-3 py-2'
                              >
                                {previewKindIcon(it.kind)}
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
                                {tpl && fid ? (
                                  <Button
                                    type='button'
                                    variant='outline'
                                    size='sm'
                                    className='inline-flex shrink-0 items-center justify-center whitespace-nowrap'
                                    onClick={() => void downloadFormTemplate(fid, tpl)}
                                  >
                                    ひな型DL
                                  </Button>
                                ) : null}
                              </li>
                            );
                          })}
                          {unpublishedMapped.map((f) => (
                            <li
                              key={`unpub-${f.id}`}
                              className='flex flex-wrap items-center gap-3 px-3 py-2'
                            >
                              <PiFileTextBold aria-hidden={true} className='size-4 text-solid-gray-600' />
                              <div className='min-w-0 flex-1'>
                                <p className='truncate text-std-16N-170 text-solid-gray-900'>
                                  {f.title}
                                </p>
                                <p className='text-dns-14N-130 text-solid-gray-500'>
                                  未公開（手続きを公開すると受付が開きます）
                                </p>
                              </div>
                              <span className='rounded-4 bg-orange-50 px-1.5 py-0.5 text-dns-14N-130 text-orange-800'>
                                未公開
                              </span>
                            </li>
                          ))}
                        </ul>
                        {unpublishedMapped.length > 0 ? (
                          <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>
                            「未公開」の書類は、手続きを公開すると自動で受付が開き、申請者に出ます。
                          </p>
                        ) : null}
                      </>
                    ) : (
                      <p className='mt-3 text-std-16N-170 text-solid-gray-700'>
                        {resolveBusy
                          ? '判定中…'
                          : '今の答えでは出る書類はありません。案内フォームの答えを選ぶと表示されます。'}
                      </p>
                    )}
                  </div>
                ) : null}
              </section>
            )}

            {error && (
              <p className='text-error-1' role='alert'>
                {error}
              </p>
            )}
            {procedure.can_edit && (
              <div
                id='pf-proc-actions'
                className='sticky bottom-0 z-10 flex flex-wrap gap-2 border-t border-solid-gray-420 bg-white py-3'
              >
                <Button type='button' variant='outline' size='md' aria-disabled={submitting} onClick={() => void onSave()}>
                  {submitting ? '保存中...' : '保存する'}
                </Button>
                {procedure.status === 'published' ? (
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    aria-disabled={submitting}
                    onClick={async () => {
                      if (
                        !window.confirm(
                          'この手続きを非公開にしますか。新しい申請は止まります。届いている申請は残ります。',
                        )
                      ) {
                        return;
                      }
                      const next = await setStatus(procedure.id, 'draft');
                      if (next) await mutate();
                    }}
                  >
                    手続きを非公開
                  </Button>
                ) : (
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    aria-disabled={submitting}
                    onClick={async () => {
                      if (
                        description.includes('【確認】') &&
                        !window.confirm(
                          '説明に【確認】が残っています。手引きのメモを直さずに公開しますか。',
                        )
                      ) {
                        return;
                      }
                      await onSave();
                      const next = await setStatus(procedure.id, 'published');
                      if (next) {
                        await mutate();
                      }
                    }}
                  >
                    手続きを公開
                  </Button>
                )}
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={submitting || procedure.status === 'published'}
                  title={
                    procedure.status === 'published'
                      ? '公開中は削除できません。先に非公開にしてください。'
                      : undefined
                  }
                  onClick={async () => {
                    if (procedure.status === 'published') return;
                    if (!window.confirm('この手続きを削除しますか。申請がある場合は削除できません。')) return;
                    const ok = await remove(procedure.id);
                    if (ok) navigate('/patchform/procedures');
                  }}
                >
                  削除
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};
