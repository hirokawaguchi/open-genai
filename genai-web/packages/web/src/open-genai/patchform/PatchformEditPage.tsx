import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { LayoutBody } from '@/layout/LayoutBody';
import { CatalogPalette } from './builder/CatalogPalette';
import { CatalogTypeIcon } from './builder/CatalogTypeIcon';
import { ComponentSettings } from './builder/ComponentSettings';
import { PATCHFORM_LABEL, catalogTypeHelp } from './labels';
import { FillForm } from './runtime/FillForm';
import { DEFAULT_IMI, DEFAULT_IMI_SUBFIELDS } from './runtime/imiSuggest';
import type { CatalogItem, FormComponent, FormDefinition, IdentityMode } from './types';
import {
  extractPatchformFile,
  lookupPatchformCorporate,
  lookupPatchformPostal,
  usePatchformActions,
  usePatchformAssist,
  usePatchformConfig,
  usePatchformDetail,
} from './usePatchform';

const newId = () => `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;

const blankComponent = (type: string, catalog: CatalogItem[]): FormComponent => {
  const meta = catalog.find((c) => c.type === type);
  return {
    id: newId(),
    type,
    label: meta?.label || type,
    required: false,
    placeholder: '',
    properties:
      type === 'matrix_question'
        ? { rows: ['項目1', '項目2'], columns: ['はい', 'いいえ'] }
        : type === 'calculated'
          ? { formula: '0' }
          : type === 'text_display'
            ? { text: '説明文' }
            : type === 'image_display'
              ? { src: '' }
              : type === 'user_info_composite'
                ? { show_gender: true, show_birth_date: true }
                : meta?.has_options
                  ? { options: ['選択肢1', '選択肢2'] }
                  : {},
    imi_type: DEFAULT_IMI[type] || '',
    imi_subfields: DEFAULT_IMI_SUBFIELDS[type]
      ? { ...DEFAULT_IMI_SUBFIELDS[type] }
      : undefined,
  };
};

export const PatchformEditPage = () => {
  const { formId } = useParams();
  const navigate = useNavigate();
  const { config } = usePatchformConfig();
  const { form, isLoading, loadError } = usePatchformDetail(formId);
  const { update, submitting, error, setError } = usePatchformActions();
  const {
    generate,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const catalog = config?.catalog ?? [];

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState<'internal' | 'public' | 'both'>('internal');
  const [pin, setPin] = useState('');
  const [retentionDays, setRetentionDays] = useState('');
  const [allowDraft, setAllowDraft] = useState(true);
  const [allowMultiple, setAllowMultiple] = useState(true);
  const [identityMode, setIdentityMode] = useState<IdentityMode>('optional');
  const [editorIds, setEditorIds] = useState('');
  const [viewerIds, setViewerIds] = useState('');
  const [components, setComponents] = useState<FormComponent[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown>>({});
  const [aiText, setAiText] = useState('');
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [pane, setPane] = useState<'edit' | 'preview'>('edit');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!form) return;
    setTitle(form.title);
    setDescription(form.description || '');
    setVisibility(form.visibility);
    setRetentionDays(String(form.retention_days ?? ''));
    setAllowDraft(form.allow_draft !== false);
    setAllowMultiple(form.allow_multiple !== false);
    setIdentityMode(form.identity_mode || 'optional');
    setEditorIds((form.editor_user_ids ?? []).join('\n'));
    setViewerIds((form.viewer_user_ids ?? []).join('\n'));
    setComponents(form.definition.components);
    setSelectedId(form.definition.components[0]?.id ?? null);
  }, [form]);

  const addComponent = (type: string) => {
    const next = blankComponent(type, catalog);
    setComponents((prev) => [...prev, next]);
    setSelectedId(next.id);
  };

  const moveComponent = (idx: number, dir: -1 | 1) => {
    setComponents((prev) => {
      const to = idx + dir;
      if (to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      [next[to], next[idx]] = [next[idx], next[to]];
      return next;
    });
  };

  const selected = components.find((c) => c.id === selectedId) ?? null;

  const definition = (): FormDefinition => ({
    $version: config?.spec_version || 'opengenai-patchform/1',
    metadata: { title, description },
    components,
  });

  const onSave = async () => {
    if (!formId) return;
    setError(null);
    const detail = await update(formId, {
      title,
      description,
      visibility,
      definition: definition(),
      pin: pin.trim() || undefined,
      retention_days: retentionDays.trim() ? Number(retentionDays) : undefined,
      allow_draft: allowDraft,
      allow_multiple: allowMultiple,
      identity_mode: identityMode,
      ...(form?.role === 'owner' || form?.role === 'admin'
        ? {
            editor_user_ids: editorIds.split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
            viewer_user_ids: viewerIds.split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
          }
        : {}),
    });
    if (detail) navigate(`/patchform/${formId}`);
  };

  return (
    <LayoutBody>
      <PageTitle title={`${PATCHFORM_LABEL}を編集`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '編集' },
          ]}
        />
        <h1 className='text-std-20B-160 lg:text-std-24B-150'>フォームを編集</h1>
        {form && form.can_edit === false && (
          <p className='text-error-1' role='alert'>
            このフォームを編集する権限がありません。
          </p>
        )}
        {form && (form.status === 'published' || form.status === 'closed') && (
          <p className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3 text-std-16N-170 text-solid-gray-800'>
            保存は下書きです。部品の追加・削除・種類変更は、詳細画面で
            {form.status === 'closed' ? '再公開' : '「公開版に反映」'}
            するまで回答者には見えません。
            {(form.submission_count ?? 0) > 0
              ? ` 既存の回答 ${form.submission_count} 件は、答えた当時の版のまま残ります。`
              : ''}
          </p>
        )}
        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}
        {form && (
          <>
            <div className='flex flex-wrap gap-2 border-b border-solid-gray-300' role='tablist' aria-label='編集とプレビュー'>
              {(
                [
                  { id: 'edit', label: '編集' },
                  { id: 'preview', label: 'プレビュー' },
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

            {pane === 'edit' && (
              <div className='flex flex-col gap-6'>
                <Disclosure className='rounded-8 border border-solid-gray-300 px-4 py-3'>
                  <DisclosureSummary>
                    <span className='text-std-16B-150'>フォーム設定（タイトル・公開範囲）</span>
                  </DisclosureSummary>
                  <div className='mt-3 flex flex-col gap-4'>
                    <div className='grid gap-4 md:grid-cols-2'>
                      <div>
                        <Label htmlFor='pf-edit-title' size='sm'>
                          タイトル
                        </Label>
                        <input
                          id='pf-edit-title'
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          value={title}
                          onChange={(e) => setTitle(e.target.value)}
                        />
                      </div>
                      <div>
                        <Label htmlFor='pf-vis' size='sm'>
                          公開範囲
                        </Label>
                        <select
                          id='pf-vis'
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          value={visibility}
                          onChange={(e) => setVisibility(e.target.value as typeof visibility)}
                        >
                          <option value='internal'>庁内のみ</option>
                          <option value='public'>外部のみ</option>
                          <option value='both'>庁内と外部</option>
                        </select>
                      </div>
                    </div>
                    <div>
                      <Label htmlFor='pf-edit-desc' size='sm'>
                        説明
                      </Label>
                      <textarea
                        id='pf-edit-desc'
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        rows={2}
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                      />
                    </div>
                    <div className='grid gap-4 md:grid-cols-2'>
                      <div>
                        <Label htmlFor='pf-pin' size='sm'>
                          外部回答用暗証番号（4桁・任意）
                        </Label>
                        <input
                          id='pf-pin'
                          className='mt-1 w-full max-w-48 rounded-4 border border-solid-gray-420 px-3 py-2'
                          inputMode='numeric'
                          maxLength={4}
                          value={pin}
                          onChange={(e) => setPin(e.target.value)}
                          placeholder={form.has_pin ? '変更する場合のみ' : ''}
                        />
                      </div>
                      <div>
                        <Label htmlFor='pf-retain' size='sm'>
                          保持日数
                        </Label>
                        <input
                          id='pf-retain'
                          className='mt-1 w-full max-w-48 rounded-4 border border-solid-gray-420 px-3 py-2'
                          inputMode='numeric'
                          value={retentionDays}
                          onChange={(e) => setRetentionDays(e.target.value)}
                        />
                      </div>
                    </div>
                    <fieldset>
                      <legend className='text-oln-16B-100'>回答者の扱い</legend>
                      <div className='mt-2 flex flex-col gap-2'>
                        {(
                          [
                            {
                              id: 'required',
                              label: '申請（記名必須）',
                              help: '誰の回答か分からないと使えません。庁内はログイン名、外部は氏名を記録します。',
                            },
                            {
                              id: 'optional',
                              label: '任意記名',
                              help: '名前があると助かりますが、空でも受け付けます。',
                            },
                            {
                              id: 'anonymous',
                              label: '匿名',
                              help: '一覧にもCSVにも名前や職員IDを出しません。',
                            },
                          ] as const
                        ).map((opt) => (
                          <label key={opt.id} className='flex items-start gap-2 text-std-16N-170'>
                            <input
                              type='radio'
                              className='mt-1'
                              name='pf-identity'
                              checked={identityMode === opt.id}
                              onChange={() => setIdentityMode(opt.id)}
                            />
                            <span>
                              {opt.label}
                              <span className='block text-dns-14N-130 text-solid-gray-600'>
                                {opt.help}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <div className='flex flex-col gap-2'>
                      <label className='flex items-center gap-2 text-std-16N-170'>
                        <input
                          type='checkbox'
                          checked={allowDraft}
                          onChange={(e) => setAllowDraft(e.target.checked)}
                        />
                        途中の下書き保存を許可する
                      </label>
                      <label className='flex items-center gap-2 text-std-16N-170'>
                        <input
                          type='checkbox'
                          checked={allowMultiple}
                          onChange={(e) => setAllowMultiple(e.target.checked)}
                        />
                        同じ人の再提出を許可する
                      </label>
                    </div>
                    {form.role === 'owner' || form.role === 'admin' ? (
                      <div className='grid gap-4 md:grid-cols-2'>
                        <div>
                          <Label htmlFor='pf-editors' size='sm'>
                            編集できる職員（ユーザーID・1行に1つ）
                          </Label>
                          <textarea
                            id='pf-editors'
                            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                            rows={3}
                            value={editorIds}
                            onChange={(e) => setEditorIds(e.target.value)}
                            placeholder='例: staff01'
                          />
                        </div>
                        <div>
                          <Label htmlFor='pf-viewers' size='sm'>
                            回答だけ見られる職員（ユーザーID・1行に1つ）
                          </Label>
                          <textarea
                            id='pf-viewers'
                            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                            rows={3}
                            value={viewerIds}
                            onChange={(e) => setViewerIds(e.target.value)}
                            placeholder='例: staff02'
                          />
                        </div>
                      </div>
                    ) : null}
                  </div>
                </Disclosure>

                <Disclosure className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-4 py-3'>
                  <DisclosureSummary>
                    <span className='text-std-16B-150'>AIで修正する</span>
                  </DisclosureSummary>
                  <div className='mt-3 flex flex-col gap-2'>
                    <Label htmlFor='pf-edit-ai' size='sm'>
                      指示
                    </Label>
                    <textarea
                      id='pf-edit-ai'
                      className='w-full rounded-4 border border-solid-gray-420 bg-white px-3 py-2'
                      rows={2}
                      value={aiText}
                      onChange={(e) => setAiText(e.target.value)}
                      placeholder='例: 振込先を追加して。メールは必須にして'
                    />
                    {(assistError || aiNotes) && (
                      <p
                        className={
                          assistError
                            ? 'text-dns-14N-130 text-error-1'
                            : 'text-dns-14N-130 text-solid-gray-700'
                        }
                        role={assistError ? 'alert' : undefined}
                      >
                        {assistError || aiNotes}
                      </p>
                    )}
                    <div>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        aria-disabled={assistBusy || !aiText.trim()}
                        onClick={async () => {
                          setAssistError(null);
                          setAiNotes(null);
                          const res = await generate({
                            text: aiText.trim(),
                            visibility,
                            definition: definition(),
                          });
                          if (!res) return;
                          setTitle(res.definition.metadata.title || title);
                          setDescription(res.definition.metadata.description || description);
                          setComponents(res.definition.components);
                          setSelectedId(res.definition.components[0]?.id ?? null);
                          setAiNotes(
                            res.notes || `${res.source === 'llm' ? 'AI' : 'テンプレート'}で反映しました。`,
                          );
                        }}
                      >
                        {assistBusy ? '生成中...' : '部品に反映'}
                      </Button>
                    </div>
                  </div>
                </Disclosure>

                <section className='grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(16rem,20rem)]'>
                  <div className='flex flex-col gap-3'>
                    <div>
                      <h2 className='text-std-18B-160'>このフォームの部品（{components.length}）</h2>
                      <p className='mt-1 text-dns-14N-130 text-solid-gray-700'>
                        並びは上から回答順です。行を選ぶと設定できます。
                      </p>
                    </div>
                    {components.length === 0 ? (
                      <p className='rounded-8 border border-dashed border-solid-gray-420 px-4 py-6 text-std-16N-170 text-solid-gray-700'>
                        まだ部品がありません。右（狭い画面では下）の分類から追加してください。
                      </p>
                    ) : (
                      <ol className='flex flex-col gap-2'>
                        {components.map((c, idx) => {
                          const meta = catalog.find((x) => x.type === c.type);
                          const open = selectedId === c.id;
                          return (
                            <li
                              key={c.id}
                              className={`overflow-hidden rounded-8 border ${
                                open ? 'border-blue-900 bg-blue-50' : 'border-solid-gray-300 bg-white'
                              }`}
                            >
                              <div className='flex flex-wrap items-center gap-2 px-3 py-2'>
                                <span className='w-6 text-dns-14N-130 text-solid-gray-600'>{idx + 1}</span>
                                <Tooltip placement='top' strategy='fixed'>
                                  <TooltipTrigger asChild>
                                    <button
                                      type='button'
                                      className='flex min-w-0 flex-1 items-start gap-2 text-left'
                                      onClick={() => setSelectedId(open ? null : c.id)}
                                    >
                                      <CatalogTypeIcon
                                        type={c.type}
                                        className='mt-0.5 size-5 text-blue-900'
                                      />
                                      <span className='min-w-0'>
                                        <span className='block text-std-16B-150 text-solid-gray-900'>
                                          {c.label || '（ラベル未設定）'}
                                          {c.required ? (
                                            <span className='ml-2 text-dns-14N-130 text-error-1'>必須</span>
                                          ) : null}
                                        </span>
                                        <span className='block text-dns-14N-130 text-solid-gray-700'>
                                          {meta?.label || c.type}
                                        </span>
                                      </span>
                                    </button>
                                  </TooltipTrigger>
                                  <TooltipContent role='tooltip' aria-hidden={true}>
                                    <span className='block max-w-64 whitespace-normal'>
                                      {catalogTypeHelp(c.type, meta?.description)}
                                    </span>
                                  </TooltipContent>
                                </Tooltip>
                                <div className='flex flex-none gap-1'>
                                  <Button
                                    type='button'
                                    variant='text'
                                    size='sm'
                                    aria-disabled={idx === 0}
                                    onClick={() => moveComponent(idx, -1)}
                                  >
                                    上へ
                                  </Button>
                                  <Button
                                    type='button'
                                    variant='text'
                                    size='sm'
                                    aria-disabled={idx === components.length - 1}
                                    onClick={() => moveComponent(idx, 1)}
                                  >
                                    下へ
                                  </Button>
                                  <Button
                                    type='button'
                                    variant='text'
                                    size='sm'
                                    onClick={() => {
                                      setComponents((prev) => prev.filter((x) => x.id !== c.id));
                                      if (selectedId === c.id) setSelectedId(null);
                                    }}
                                  >
                                    削除
                                  </Button>
                                </div>
                              </div>
                              {open && selected ? (
                                <div className='rounded-b-8 border-t border-solid-gray-300 bg-white px-3 py-3'>
                                  <ComponentSettings
                                    component={selected}
                                    catalog={catalog}
                                    siblings={components}
                                    onChange={(next) =>
                                      setComponents((prev) =>
                                        prev.map((x) => (x.id === next.id ? next : x)),
                                      )
                                    }
                                  />
                                </div>
                              ) : null}
                            </li>
                          );
                        })}
                      </ol>
                    )}
                  </div>
                  <aside className='xl:sticky xl:top-4 xl:self-start'>
                    <CatalogPalette catalog={catalog} onAdd={addComponent} />
                  </aside>
                </section>
              </div>
            )}

            {pane === 'preview' && (
              <section className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                <h2 className='text-std-20B-160'>{title || '（無題）'}</h2>
                {description ? (
                  <p className='mt-2 text-std-16N-170 text-solid-gray-700'>{description}</p>
                ) : null}
                <div className='mt-4'>
                  <FillForm
                    definition={definition()}
                    values={preview}
                    onChange={(id, v) => setPreview((p) => ({ ...p, [id]: v }))}
                    onExtract={extractPatchformFile}
                    onPostalLookup={lookupPatchformPostal}
                    onCorporateLookup={lookupPatchformCorporate}
                  />
                </div>
              </section>
            )}

            {error && (
              <p className='text-error-1' role='alert'>
                {error}
              </p>
            )}
            <div className='flex flex-wrap gap-2'>
              <Button type='button' variant='solid-fill' size='md' aria-disabled={submitting} onClick={onSave}>
                {submitting ? '保存中...' : '保存する'}
              </Button>
              <Link to={formId ? `/patchform/${formId}` : '/patchform'} className='inline-flex'>
                <Button type='button' variant='outline' size='md'>
                  戻る
                </Button>
              </Link>
            </div>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
