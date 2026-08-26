import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { PatchformSubnav } from './PatchformSubnav';
import { omitsNavigation, type ProcedureRule } from './types';
import { ProcedureSharePanel } from './ProcedureSharePanel';
import {
  usePatchformConfig,
  usePatchformList,
  usePatchformProcedure,
  usePatchformProcedureActions,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
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
  const { save, setStatus, remove, submitting, error, setError } = usePatchformProcedureActions();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [guideFormId, setGuideFormId] = useState('');
  const [notifyEmails, setNotifyEmails] = useState('');
  const [ruleMap, setRuleMap] = useState<Map<string, ProcedureRule>>(new Map());

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
  const nameLooksDraft = /[#＃]|目次/.test(name);
  const needsCopyReview = description.includes('【確認】') || nameLooksDraft;
  const hasMappedForms = collectedRules().some((r) => r.form_ids.length > 0);
  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const guideForm = forms.find((f) => f.id === guideFormId);
  const caseTags = (guideForm?.tags || []).filter((t) => t !== NAVIGATION_TAG);
  const relatedStyles = styleForms.filter((f) => (f.tags || []).some((t) => caseTags.includes(t)));
  const otherStyles = styleForms.filter((f) => !relatedStyles.some((r) => r.id === f.id));
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

            {procedure.status === 'draft' ? (
              <div className='rounded-8 border border-blue-900 bg-blue-50 px-4 py-4' role='region' aria-label='次にすること'>
                <p className='text-std-16B-150'>いまここでやること</p>
                <ol className='mt-3 flex list-decimal flex-col gap-2 pl-5 text-std-16N-170'>
                  <li>
                    <button type='button' className='text-left text-blue-900 underline-offset-2 hover:underline' onClick={() => scrollTo('pf-pe-name')}>
                      名前を、庁内の一覧で使う短い手続き名に直す
                    </button>
                    {nameLooksDraft ? (
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-700'>
                        いまは手引きの見出しが入っています。
                      </span>
                    ) : null}
                  </li>
                  <li>
                    <button type='button' className='text-left text-blue-900 underline-offset-2 hover:underline' onClick={() => scrollTo('pf-pe-desc')}>
                      説明の【確認】を読んで、残すか消すか決める
                    </button>
                  </li>
                  {!singleForm ? (
                    <li>
                      <button type='button' className='text-left text-blue-900 underline-offset-2 hover:underline' onClick={() => scrollTo('pf-mapping')}>
                        各答えのとき、申請者に出す用紙を確認する
                      </button>
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-700'>
                        「この手続きで作った用紙」にチェックします。サンプルは外して構いません。
                      </span>
                    </li>
                  ) : null}
                  <li>内容がよければ、この画面の下で保存し、公開する。</li>
                </ol>
              </div>
            ) : null}

            <PatchformProcedureCoach
              title='操作の流れ'
              defaultOpen={needsCopyReview}
              lead={
                singleForm
                  ? '申請用紙はこの1枚です。保存して公開すると受付が始まります。'
                  : 'チェックを付けた申請用紙だけが、申請者や回答者に出ます。'
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
            {procedure.status === 'published' ? (
              <div className='flex flex-col gap-2'>
                <div>
                  <Link to={`/patchform/apply/${procedure.id}`} className='inline-flex'>
                    <Button type='button' variant='solid-fill' size='sm'>
                      庁内から申請する
                    </Button>
                  </Link>
                </div>
                <ProcedureSharePanel procedureId={procedure.id} name={procedure.name} />
              </div>
            ) : null}

            <section id='pf-mapping' className='flex flex-col gap-4'>
              <h2 className='text-std-18B-160'>
                {singleForm ? '申請用紙' : '答えと申請用紙の対応'}
              </h2>
              {singleForm ? (
                <div className='rounded-8 border border-solid-gray-300 px-4 py-3'>
                  <p className='text-solid-gray-700'>
                    ナビゲーションフォームは使いません。申請者や回答者には、この1枚だけが出ます。
                  </p>
                  {procedure.guide_form_id ? (
                    <p className='mt-2'>
                      <Link
                        to={`/patchform/${procedure.guide_form_id}/edit`}
                        className='text-blue-900 underline-offset-2 hover:underline'
                      >
                        申請用紙を編集する
                      </Link>
                    </p>
                  ) : null}
                </div>
              ) : (
              <>
              <p className='text-std-16N-170 text-solid-gray-700'>
                申請者がその答えを選んだとき、追加で出す用紙にチェックします。チェックしない用紙は、その答えでは出ません。
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
                        const formGroups = [
                          { heading: 'この手続きで作った用紙', items: relatedStyles },
                          { heading: 'ほかのフォーム（サンプルなど）', items: otherStyles },
                        ].filter((group) => group.items.length > 0);
                        const groups = formGroups.length ? formGroups : [{ heading: '申請用紙', items: styleForms }];
                        return (
                          <div key={option} className='border-t border-solid-gray-300 pt-3'>
                            <p className='text-std-16B-150'>
                              答えが「{item.label}」
                              {item.label !== item.value ? `（${item.value}）` : ''}
                              のとき
                            </p>
                            <fieldset className='mt-2'>
                              <legend className='text-dns-14N-130 text-solid-gray-700'>
                                このとき出す申請用紙
                              </legend>
                              <div className='mt-1 flex flex-col gap-3'>
                                {groups.map((group) => (
                                  <div key={group.heading}>
                                    <p className='text-dns-14N-130 text-solid-gray-600'>{group.heading}</p>
                                    <div className='mt-1 flex flex-col gap-1'>
                                      {group.items.map((f) => {
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
                                            {f.title}
                                          </label>
                                        );
                                      })}
                                    </div>
                                  </div>
                                ))}
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
                            <div className='mt-2'>
                              <Label htmlFor={`prep-${field.id}-${option}`} size='sm'>
                                準備するもの（1行1つ）
                              </Label>
                              <textarea
                                id={`prep-${field.id}-${option}`}
                                className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                                rows={2}
                                value={(rule?.prepare || []).join('\n')}
                                disabled={!procedure.can_edit}
                                onChange={(e) =>
                                  updateRule(field.id, option, {
                                    prepare: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                                  })
                                }
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
              )}
            </section>

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
                {procedure.status === 'draft' ? (
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
                    {procedure.guide_status === 'closed' ? '再公開する' : '公開する'}
                  </Button>
                ) : (
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    aria-disabled={submitting}
                    onClick={async () => {
                      if (
                        !window.confirm(
                          '受付を終了しますか。新しい申請は止まります。届いている申請は残ります。',
                        )
                      ) {
                        return;
                      }
                      const next = await setStatus(procedure.id, 'draft');
                      if (next) await mutate();
                    }}
                  >
                    受付を終了
                  </Button>
                )}
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={submitting || procedure.status === 'published'}
                  title={
                    procedure.status === 'published'
                      ? '公開中は削除できません。先に受付を終了してください。'
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

            <p className='text-std-16N-170 text-solid-gray-700'>
              届いた申請は申請受付で見ます。
            </p>
            <div>
              <Link to={`/patchform/inbox/${encodeURIComponent(procedure.id)}`} className='inline-flex'>
                <Button type='button' variant='outline' size='sm'>
                  申請受付を開く
                </Button>
              </Link>
            </div>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
