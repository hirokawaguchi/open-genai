import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { answerRows } from './runtime/formatAnswer';
import type { ApplicationItem } from './types';
import {
  downloadApplicationExport,
  usePatchformApplication,
  usePatchformApplicationItems,
  usePatchformProcedureCatalog,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  none: '未充足',
  draft: '記入中',
  submitted: '提出済',
  withdrawn: '取下げ',
};

const kindLabel: Record<string, string> = {
  data: '記入必須',
  yoshiki: '様式',
  attach: '添付',
};

export const PatchformApplicationPage = () => {
  const { applicationId } = useParams();
  const { application, isLoading, loadError, mutate } = usePatchformApplication(applicationId);
  const { slots: catalogSlots } = usePatchformProcedureCatalog(application?.procedure_id);
  const { addItem, fulfillWithFile, clearFile, busy, error: itemError } =
    usePatchformApplicationItems();
  const notice = application?.notice;
  const [exporting, setExporting] = useState<'csv' | 'jsonl' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [catalogPick, setCatalogPick] = useState('');
  const [attachTitle, setAttachTitle] = useState('');
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const download = async (format: 'csv' | 'jsonl') => {
    if (!applicationId) return;
    setExporting(format);
    setExportError(null);
    try {
      await downloadApplicationExport(applicationId, format);
    } catch {
      setExportError('この申請を書き出せませんでした。');
    } finally {
      setExporting(null);
    }
  };

  const items = application?.items ?? [];
  const aid = application?.id;

  const onAddCatalog = async () => {
    if (!aid || !catalogPick) return;
    const updated = await addItem(aid, { form_id: catalogPick });
    if (updated) {
      setCatalogPick('');
      await mutate(updated, { revalidate: false });
    }
  };

  const onAddAttach = async () => {
    if (!aid || !attachTitle.trim()) return;
    const updated = await addItem(aid, { title: attachTitle.trim() });
    if (updated) {
      setAttachTitle('');
      await mutate(updated, { revalidate: false });
    }
  };

  const onDuplicate = async (item: ApplicationItem) => {
    if (!aid) return;
    const updated = await addItem(aid, { duplicate_of: item.id });
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onPickFile = async (item: ApplicationItem, file: File | undefined) => {
    if (!aid || !file) return;
    const updated = await fulfillWithFile(aid, item.id, file);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onClearFile = async (item: ApplicationItem) => {
    if (!aid) return;
    const updated = await clearFile(aid, item.id);
    if (updated) await mutate(updated, { revalidate: false });
  };

  return (
    <LayoutBody>
      <PageTitle title={application?.procedure_name || '申請'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '申請受付', to: '/patchform/inbox' },
            ...(application?.procedure_id
              ? [{ label: application.procedure_name, to: `/patchform/inbox/${application.procedure_id}` }]
              : []),
            { label: application?.token || '申請' },
          ]}
        />
        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}
        {application && (
          <>
            <div className='flex flex-col gap-2'>
              <h1 className='text-std-20B-160 lg:text-std-24B-150'>{application.procedure_name}</h1>
              <p className='text-std-16N-170 text-solid-gray-700'>
                案内番号: {application.token}。このセットで始めてください。足りなければ足せます。
              </p>
              {application.procedure_description && (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  {application.procedure_description}
                </p>
              )}
              <p className='text-dns-14N-130 text-solid-gray-600'>公開 URL: {application.public_url}</p>
              <div className='mt-2 flex flex-wrap gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={exporting != null}
                  onClick={() => void download('csv')}
                >
                  {exporting === 'csv' ? '書き出し中...' : 'CSVをダウンロード'}
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={exporting != null}
                  onClick={() => void download('jsonl')}
                >
                  {exporting === 'jsonl' ? '書き出し中...' : 'JSONLをダウンロード'}
                </Button>
              </div>
              {exportError && (
                <p className='text-error-1' role='alert'>
                  {exportError}
                </p>
              )}
            </div>
            <PatchformProcedureCoach
              title='この申請でやること'
              lead='様式はオンライン記入でも、記入済みファイルの添付でも構いません。足りなければ枠を足せます。'
              steps={[
                {
                  id: 'open',
                  label: '未充足の枠を満たす',
                  done: items.length === 0 || items.every((f) => f.status === 'submitted'),
                  hint: '庁内から開いても、公開 URL から開いても同じ束に付きます。',
                  action: (() => {
                    const next = items.find(
                      (f) => f.can_fill_online && (f.status === 'none' || f.status === 'draft'),
                    );
                    return next
                      ? {
                          label: `「${next.title}」を記入する`,
                          to: `/patchform/${next.form_id}?app=${encodeURIComponent(application.token)}&item=${encodeURIComponent(next.id)}`,
                        }
                      : undefined;
                  })(),
                },
                {
                  id: 'done',
                  label: '必要な枠を満たし終える',
                  done: items.length > 0 && items.every((f) => f.status === 'submitted'),
                  hint: `${items.filter((f) => f.status === 'submitted').length} / ${items.length} 充足`,
                },
              ]}
            />
            {(notice?.notes || []).length > 0 && (
              <section>
                <h2 className='text-std-18B-160'>解説</h2>
                <ul className='mt-2 list-disc pl-5 text-std-16N-170'>
                  {notice?.notes?.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </section>
            )}
            {(notice?.prepare || []).length > 0 && (
              <section>
                <h2 className='text-std-18B-160'>準備するもの</h2>
                <ul className='mt-2 list-disc pl-5 text-std-16N-170'>
                  {notice?.prepare?.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </section>
            )}
            <section>
              <h2 className='text-std-18B-160'>提出物（作業台）</h2>
              {itemError && (
                <p className='mt-2 text-error-1' role='alert'>
                  {itemError}
                </p>
              )}
              {items.length === 0 ? (
                <p className='mt-2 text-solid-gray-600'>この回答では推奨する枠がありません。下から足せます。</p>
              ) : (
                <ul className='mt-2 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                  {items.map((f) => {
                    const rows =
                      f.status === 'submitted' && f.definition && f.answers
                        ? answerRows(f.definition.components, f.answers)
                        : [];
                    const filled = f.fulfillment === 'file';
                    return (
                      <li key={f.id} className='py-3'>
                        <div className='flex flex-wrap items-baseline gap-2'>
                          {f.can_fill_online && !filled ? (
                            <Link
                              to={`/patchform/${f.form_id}?app=${encodeURIComponent(application.token)}&item=${encodeURIComponent(f.id)}`}
                              className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                            >
                              {f.title}
                              {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                            </Link>
                          ) : (
                            <span className='text-std-16B-150'>
                              {f.title}
                              {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                            </span>
                          )}
                          <span className='rounded bg-solid-gray-100 px-2 py-0.5 text-dns-14N-130 text-solid-gray-700'>
                            {kindLabel[f.kind] || f.kind}
                          </span>
                        </div>
                        <p className='text-dns-14N-130 text-solid-gray-600'>
                          {statusLabel[f.status] || f.status}
                          {filled && f.file_name ? ` / 添付: ${f.file_name}` : ''}
                          {f.receipt_code ? ` / 控え番号 ${f.receipt_code}` : ''}
                          {f.submitted_at ? ` / ${new Date(f.submitted_at).toLocaleString('ja-JP')}` : ''}
                        </p>
                        {rows.length > 0 ? (
                          <dl className='mt-2 grid gap-1 text-std-16N-170'>
                            {rows.map((row) => (
                              <div key={row.id} className='grid gap-0.5 sm:grid-cols-[12rem_1fr]'>
                                <dt className='text-solid-gray-600'>{row.label}</dt>
                                <dd className='whitespace-pre-wrap text-solid-gray-900'>{row.value}</dd>
                              </div>
                            ))}
                          </dl>
                        ) : null}
                        {f.kind !== 'data' && (
                          <div className='mt-2 flex flex-wrap gap-2'>
                            {filled ? (
                              <Button
                                type='button'
                                variant='outline'
                                size='sm'
                                aria-disabled={busy}
                                onClick={() => void onClearFile(f)}
                              >
                                添付を取り消す
                              </Button>
                            ) : (
                              <>
                                <input
                                  ref={(el) => {
                                    fileInputs.current[f.id] = el;
                                  }}
                                  type='file'
                                  className='hidden'
                                  onChange={(e) => void onPickFile(f, e.target.files?.[0])}
                                />
                                <Button
                                  type='button'
                                  variant='outline'
                                  size='sm'
                                  aria-disabled={busy}
                                  onClick={() => fileInputs.current[f.id]?.click()}
                                >
                                  記入済みファイルを添付する
                                </Button>
                              </>
                            )}
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              aria-disabled={busy}
                              onClick={() => void onDuplicate(f)}
                            >
                              同じ枠をもう1件
                            </Button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            <section className='flex flex-col gap-4 rounded-lg border border-solid-gray-300 p-4'>
              <h2 className='text-std-16B-150'>枠を足す</h2>
              {catalogSlots.filter((s) => s.form_id).length > 0 && (
                <div className='flex flex-wrap items-center gap-2'>
                  <label className='text-std-16N-170 text-solid-gray-700' htmlFor='catalog-pick'>
                    別の様式を足す
                  </label>
                  <select
                    id='catalog-pick'
                    className='rounded border border-solid-gray-400 px-2 py-1 text-std-16N-170'
                    value={catalogPick}
                    onChange={(e) => setCatalogPick(e.target.value)}
                  >
                    <option value=''>選択してください</option>
                    {catalogSlots
                      .filter((s) => s.form_id)
                      .map((s) => (
                        <option key={s.slot_id} value={s.form_id ?? ''}>
                          {s.title}
                        </option>
                      ))}
                  </select>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={busy || !catalogPick}
                    onClick={() => void onAddCatalog()}
                  >
                    足す
                  </Button>
                </div>
              )}
              <div className='flex flex-wrap items-center gap-2'>
                <label className='text-std-16N-170 text-solid-gray-700' htmlFor='attach-title'>
                  添付を足す
                </label>
                <input
                  id='attach-title'
                  className='rounded border border-solid-gray-400 px-2 py-1 text-std-16N-170'
                  placeholder='例: 住民票の写し'
                  value={attachTitle}
                  onChange={(e) => setAttachTitle(e.target.value)}
                />
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={busy || !attachTitle.trim()}
                  onClick={() => void onAddAttach()}
                >
                  足す
                </Button>
              </div>
            </section>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
