import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { FillForm } from './runtime/FillForm';
import type { CatalogItem, FormComponent, FormDefinition } from './types';
import {
  extractPatchformFile,
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
              : meta?.has_options
                ? { options: ['選択肢1', '選択肢2'] }
                : {},
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
  const [components, setComponents] = useState<FormComponent[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown>>({});
  const [addType, setAddType] = useState('text');
  const [aiText, setAiText] = useState('');
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [pane, setPane] = useState<'edit' | 'preview'>('edit');

  useEffect(() => {
    if (!form) return;
    setTitle(form.title);
    setDescription(form.description || '');
    setVisibility(form.visibility);
    setRetentionDays(String(form.retention_days ?? ''));
    setComponents(form.definition.components);
  }, [form]);

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

            <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
              <Label htmlFor='pf-edit-ai' size='sm'>
                AIで修正する
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
                    assistError ? 'text-dns-14N-130 text-error-1' : 'text-dns-14N-130 text-solid-gray-700'
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
                    setAiNotes(res.notes || `${res.source === 'llm' ? 'AI' : 'テンプレート'}で反映しました。`);
                  }}
                >
                  {assistBusy ? '生成中...' : '部品に反映'}
                </Button>
              </div>
            </div>

            <section className='flex flex-col gap-3'>
              <h2 className='text-std-18B-160'>部品</h2>
              <div className='flex flex-wrap items-end gap-2'>
                <div>
                  <Label htmlFor='pf-add-type' size='sm'>
                    追加する部品
                  </Label>
                  <select
                    id='pf-add-type'
                    className='mt-1 rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={addType}
                    onChange={(e) => setAddType(e.target.value)}
                  >
                    {catalog.map((c) => (
                      <option key={c.type} value={c.type}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => setComponents((prev) => [...prev, blankComponent(addType, catalog)])}
                >
                  追加
                </Button>
              </div>
              {components.map((c, idx) => (
                <div key={c.id} className='rounded-8 border border-solid-gray-300 p-3'>
                  <div className='grid gap-3 md:grid-cols-2'>
                    <div>
                      <Label size='sm'>ラベル</Label>
                      <input
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={c.label}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) => (x.id === c.id ? { ...x, label: e.target.value } : x)),
                          )
                        }
                      />
                    </div>
                    <div>
                      <Label size='sm'>種類</Label>
                      <p className='mt-2 text-std-16N-170 text-solid-gray-700'>
                        {catalog.find((x) => x.type === c.type)?.label || c.type}
                      </p>
                    </div>
                    <div>
                      <Label size='sm'>プレースホルダ</Label>
                      <input
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={c.placeholder || ''}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) => (x.id === c.id ? { ...x, placeholder: e.target.value } : x)),
                          )
                        }
                      />
                    </div>
                    <label className='mt-6 flex items-center gap-2 text-std-14N-160'>
                      <input
                        type='checkbox'
                        checked={!!c.required}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) => (x.id === c.id ? { ...x, required: e.target.checked } : x)),
                          )
                        }
                      />
                      必須
                    </label>
                  </div>
                  {c.type === 'matrix_question' && (
                    <div className='mt-2 grid gap-2 md:grid-cols-2'>
                      <div>
                        <Label size='sm'>行（改行区切り）</Label>
                        <textarea
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          rows={3}
                          value={((c.properties?.rows as string[]) || []).join('\n')}
                          onChange={(e) =>
                            setComponents((prev) =>
                              prev.map((x) =>
                                x.id === c.id
                                  ? {
                                      ...x,
                                      properties: {
                                        ...x.properties,
                                        rows: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                                      },
                                    }
                                  : x,
                              ),
                            )
                          }
                        />
                      </div>
                      <div>
                        <Label size='sm'>列（改行区切り）</Label>
                        <textarea
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          rows={3}
                          value={((c.properties?.columns as string[]) || []).join('\n')}
                          onChange={(e) =>
                            setComponents((prev) =>
                              prev.map((x) =>
                                x.id === c.id
                                  ? {
                                      ...x,
                                      properties: {
                                        ...x.properties,
                                        columns: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                                      },
                                    }
                                  : x,
                              ),
                            )
                          }
                        />
                      </div>
                    </div>
                  )}
                  {c.type === 'text_display' && (
                    <div className='mt-2'>
                      <Label size='sm'>説明文</Label>
                      <textarea
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        rows={3}
                        value={String(c.properties?.text || '')}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) =>
                              x.id === c.id
                                ? { ...x, properties: { ...x.properties, text: e.target.value } }
                                : x,
                            ),
                          )
                        }
                      />
                    </div>
                  )}
                  {c.type === 'image_display' && (
                    <div className='mt-2'>
                      <Label size='sm'>画像 URL（https または data:image）</Label>
                      <input
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={String(c.properties?.src || '')}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) =>
                              x.id === c.id
                                ? { ...x, properties: { ...x.properties, src: e.target.value } }
                                : x,
                            ),
                          )
                        }
                      />
                    </div>
                  )}
                  {c.type === 'calculated' && (
                    <div className='mt-2'>
                      <Label size='sm'>計算式（例: {'{{qty}} * 100'}）</Label>
                      <input
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={String(c.properties?.formula || '')}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) =>
                              x.id === c.id
                                ? { ...x, properties: { ...x.properties, formula: e.target.value } }
                                : x,
                            ),
                          )
                        }
                      />
                    </div>
                  )}
                  <div className='mt-2'>
                    <Label size='sm'>IMI 語彙（任意）</Label>
                    <input
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                      list='pf-imi-presets'
                      value={c.imi_type || ''}
                      onChange={(e) =>
                        setComponents((prev) =>
                          prev.map((x) => (x.id === c.id ? { ...x, imi_type: e.target.value } : x)),
                        )
                      }
                      placeholder='例: ic:住所'
                    />
                    <datalist id='pf-imi-presets'>
                      <option value='ic:氏名' />
                      <option value='ic:氏名カナ' />
                      <option value='ic:住所' />
                      <option value='ic:郵便番号' />
                      <option value='ic:メールアドレス' />
                      <option value='ic:電話番号' />
                      <option value='ic:生年月日' />
                      <option value='ic:法人番号' />
                    </datalist>
                  </div>
                  <div className='mt-2 grid gap-2 md:grid-cols-2'>
                    <div>
                      <Label size='sm'>表示条件の部品</Label>
                      <select
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={!Array.isArray(c.visibleWhen) && c.visibleWhen?.field ? c.visibleWhen.field : ''}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) =>
                              x.id === c.id
                                ? {
                                    ...x,
                                    visibleWhen: e.target.value
                                      ? {
                                          field: e.target.value,
                                          eq: !Array.isArray(x.visibleWhen) ? x.visibleWhen?.eq || '' : '',
                                        }
                                      : undefined,
                                  }
                                : x,
                            ),
                          )
                        }
                      >
                        <option value=''>常に表示</option>
                        {components
                          .filter((x) => x.id !== c.id)
                          .map((x) => (
                            <option key={x.id} value={x.id}>
                              {x.label || x.id}
                            </option>
                          ))}
                      </select>
                    </div>
                    {!Array.isArray(c.visibleWhen) && c.visibleWhen?.field ? (
                      <div>
                        <Label size='sm'>この値のとき表示</Label>
                        <input
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          value={c.visibleWhen.eq || ''}
                          onChange={(e) =>
                            setComponents((prev) =>
                              prev.map((x) =>
                                x.id === c.id && !Array.isArray(x.visibleWhen) && x.visibleWhen
                                  ? { ...x, visibleWhen: { ...x.visibleWhen, eq: e.target.value } }
                                  : x,
                              ),
                            )
                          }
                        />
                      </div>
                    ) : null}
                  </div>
                  {catalog.find((x) => x.type === c.type)?.has_options && (
                    <div className='mt-2'>
                      <Label size='sm'>選択肢（改行区切り）</Label>
                      <textarea
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        rows={3}
                        value={(c.properties?.options || []).join('\n')}
                        onChange={(e) =>
                          setComponents((prev) =>
                            prev.map((x) =>
                              x.id === c.id
                                ? {
                                    ...x,
                                    properties: {
                                      ...x.properties,
                                      options: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                                    },
                                  }
                                : x,
                            ),
                          )
                        }
                      />
                    </div>
                  )}
                  <div className='mt-2 flex gap-2'>
                    <Button
                      type='button'
                      variant='text'
                      size='sm'
                      aria-disabled={idx === 0}
                      onClick={() =>
                        setComponents((prev) => {
                          if (idx === 0) return prev;
                          const next = [...prev];
                          [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
                          return next;
                        })
                      }
                    >
                      上へ
                    </Button>
                    <Button
                      type='button'
                      variant='text'
                      size='sm'
                      aria-disabled={idx === components.length - 1}
                      onClick={() =>
                        setComponents((prev) => {
                          if (idx >= prev.length - 1) return prev;
                          const next = [...prev];
                          [next[idx + 1], next[idx]] = [next[idx], next[idx + 1]];
                          return next;
                        })
                      }
                    >
                      下へ
                    </Button>
                    <Button
                      type='button'
                      variant='text'
                      size='sm'
                      onClick={() => setComponents((prev) => prev.filter((x) => x.id !== c.id))}
                    >
                      削除
                    </Button>
                  </div>
                </div>
              ))}
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
