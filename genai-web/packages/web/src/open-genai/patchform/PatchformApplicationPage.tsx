import { useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import {
  PiArrowDownBold,
  PiArrowUpBold,
  PiCheckCircleFill,
  PiFileTextBold,
  PiNotePencilBold,
  PiPaperclipBold,
  PiSignpostBold,
} from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { DOCMAKER_LABEL } from '../docmaker/labels';
import { PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { answerRows } from './runtime/formatAnswer';
import type { ApplicationItem } from './types';
import {
  downloadApplicationExport,
  downloadItemTemplate,
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

const kindIcon = (kind: string) => {
  if (kind === 'attach') return PiPaperclipBold;
  if (kind === 'data') return PiNotePencilBold;
  return PiFileTextBold;
};

const statusTone: Record<string, string> = {
  submitted: 'text-green-800',
  draft: 'text-blue-900',
  withdrawn: 'text-error-1',
  none: 'text-solid-gray-500',
};

export const PatchformApplicationPage = () => {
  const { applicationId } = useParams();
  const [searchParams] = useSearchParams();
  // マイ手続き（本人）経由か、申請受付（レビュー）経由かでパンくずを出し分ける。
  const fromMy = searchParams.get('from') === 'my';
  const { application, isLoading, loadError, mutate } = usePatchformApplication(applicationId);
  const { slots: catalogSlots } = usePatchformProcedureCatalog(application?.procedure_id);
  const { addItem, fulfillWithFile, clearFile, setSource, reorder, busy, error: itemError } =
    usePatchformApplicationItems();
  const notice = application?.notice;
  const [exporting, setExporting] = useState<'csv' | 'jsonl' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [catalogPick, setCatalogPick] = useState('');
  const [attachTitle, setAttachTitle] = useState('');
  const [condOpen, setCondOpen] = useState(true);
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

  const allItems = application?.items ?? [];
  // 案内（ナビ）は提出書類ではないので一覧から分け、上部の「申請条件」に集約する。
  const navItem = allItems.find((it) => it.kind === 'data') ?? null;
  const items = allItems.filter((it) => it.kind !== 'data');
  const aid = application?.id;
  const navRows =
    navItem?.status === 'submitted' && navItem.definition && navItem.answers
      ? answerRows(navItem.definition.components, navItem.answers)
      : [];
  // 「条件を変更」は案内フォームを直接開かず、作成時と同じウィザードを既存
  // プロジェクト編集モード（?app=）で開く。回答は現在の内容が引き継がれる。
  const condWizardTo =
    application?.procedure_id && aid
      ? `/patchform/apply/${application.procedure_id}/wizard?app=${encodeURIComponent(aid)}&from=my`
      : navItem?.form_id
        ? `/patchform/${navItem.form_id}?app=${encodeURIComponent(application?.token ?? '')}&item=${encodeURIComponent(navItem.id)}${fromMy ? '&from=my' : ''}`
        : null;

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

  const onSetSource = async (item: ApplicationItem, source: 'form' | 'file') => {
    if (!aid) return;
    const updated = await setSource(aid, item.id, source);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onMove = async (index: number, dir: 'up' | 'down') => {
    if (!aid) return;
    const j = dir === 'up' ? index - 1 : index + 1;
    if (j < 0 || j >= items.length) return;
    const next = [...items];
    [next[index], next[j]] = [next[j], next[index]];
    // ナビ（案内）は先頭に固定し、提出書類の並びだけを保存する。
    const order = [...(navItem ? [navItem.id] : []), ...next.map((it) => it.id)];
    const updated = await reorder(aid, order);
    if (updated) await mutate(updated, { revalidate: false });
  };

  return (
    <LayoutBody>
      <PageTitle title={application?.procedure_name || '申請'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={
            fromMy
              ? [
                  { label: 'ホーム', to: '/' },
                  { label: 'AIアプリ', to: '/apps' },
                  { label: DOCMAKER_LABEL, to: '/docmaker' },
                  {
                    label:
                      application?.title || application?.procedure_name || '手続き',
                  },
                ]
              : [
                  { label: 'ホーム', to: '/' },
                  { label: 'AIアプリ', to: '/apps' },
                  { label: PATCHFORM_LABEL, to: '/patchform' },
                  { label: '申請受付', to: '/patchform/inbox' },
                  ...(application?.procedure_id
                    ? [
                        {
                          label: application.procedure_name,
                          to: `/patchform/inbox/${application.procedure_id}`,
                        },
                      ]
                    : []),
                  { label: application?.token || '申請' },
                ]
          }
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
              <div className='flex flex-wrap items-center gap-2'>
                <h1 className='text-std-20B-160 lg:text-std-24B-150'>
                  {application.title || application.procedure_name}
                </h1>
                {application.status && (
                  <span
                    className={`rounded-4 border px-2 py-0.5 text-dns-14N-130 ${
                      application.status.effective === '提出済' ||
                      application.status.effective === '完了'
                        ? 'border-green-600 bg-green-50 text-green-800'
                        : application.status.effective === '作業中'
                          ? 'border-blue-900 bg-blue-50 text-blue-900'
                          : application.status.effective === '取下げ'
                            ? 'border-error-1 bg-red-50 text-error-1'
                            : 'border-solid-gray-420 bg-solid-gray-50 text-solid-gray-700'
                    }`}
                  >
                    {application.status.effective}
                  </span>
                )}
              </div>
              <p className='text-std-16N-170 text-solid-gray-700'>
                案内番号: {application.token}。このセットで始めてください。足りなければ足せます。
              </p>
              {application.procedure_description && (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  {application.procedure_description}
                </p>
              )}
              <p className='text-dns-14N-130 text-solid-gray-600'>公開 URL: {application.public_url}</p>
            </div>
            {navItem && (
              <section className='flex flex-col gap-3 rounded-8 border border-blue-900/40 bg-blue-50/50 p-4'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <button
                    type='button'
                    className='flex items-center gap-2 text-std-18B-160 text-blue-900'
                    aria-expanded={condOpen}
                    onClick={() => setCondOpen((v) => !v)}
                  >
                    <PiSignpostBold className='size-5' />
                    申請条件（案内の回答）
                    <span className='text-dns-14N-130 text-blue-900/70'>
                      {condOpen ? '（閉じる）' : '（開く）'}
                    </span>
                  </button>
                  {condWizardTo && (
                    <Link to={condWizardTo} className='inline-flex'>
                      <Button type='button' variant='outline' size='sm'>
                        {navRows.length > 0 ? '条件を変更' : '条件を入力'}
                      </Button>
                    </Link>
                  )}
                </div>
                {condOpen && (
                  <div className='flex flex-col gap-4'>
                    {navRows.length > 0 ? (
                      <dl className='grid gap-1 text-std-16N-170 sm:grid-cols-[10rem_1fr]'>
                        {navRows.map((row) => (
                          <div key={row.id} className='contents'>
                            <dt className='text-solid-gray-600'>{row.label}</dt>
                            <dd className='whitespace-pre-wrap text-solid-gray-900'>{row.value}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : (
                      <p className='text-std-16N-170 text-solid-gray-700'>
                        案内に答えると、この申請に必要な書類が提出書類一覧に並びます。
                      </p>
                    )}
                    {(notice?.notes || []).length > 0 && (
                      <div className='rounded-8 border border-blue-900/20 bg-white/70 p-3'>
                        <h3 className='text-std-16B-150 text-solid-gray-900'>解説</h3>
                        <ul className='mt-1 list-disc pl-5 text-std-16N-170 text-solid-gray-800'>
                          {notice?.notes?.map((n) => (
                            <li key={n}>{n}</li>
                          ))}
                        </ul>
                        <p className='mt-2 text-dns-14N-130 text-solid-gray-500'>
                          解説は、選んだ条件（案内の回答）ごとに手続き側で用意された補足です。
                        </p>
                      </div>
                    )}
                    {(notice?.prepare || []).length > 0 && (
                      <div className='rounded-8 border border-blue-900/20 bg-white/70 p-3'>
                        <h3 className='text-std-16B-150 text-solid-gray-900'>準備するもの</h3>
                        <ul className='mt-1 list-disc pl-5 text-std-16N-170 text-solid-gray-800'>
                          {notice?.prepare?.map((n) => (
                            <li key={n}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </section>
            )}
            <section className='flex flex-col gap-2'>
              <div className='flex flex-wrap items-baseline justify-between gap-2'>
                <h2 className='text-std-18B-160'>提出書類一覧</h2>
                {items.length > 0 && (
                  <span className='text-dns-14N-130 text-solid-gray-600'>
                    {items.filter((f) => f.status === 'submitted').length} / {items.length} 充足
                  </span>
                )}
              </div>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                初期の並び順は「案内で必要になった様式 → 準備するもの（添付） → あとから足した枠」の順です。左の
                ↑↓ で申請しやすい順に並び替えできます。
              </p>
              {itemError && (
                <p className='text-error-1' role='alert'>
                  {itemError}
                </p>
              )}
              {items.length === 0 ? (
                <p className='text-solid-gray-600'>この回答では推奨する枠がありません。操作方法から足せます。</p>
              ) : (
                <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
                  <table className='w-full min-w-[calc(780/16*1rem)] border-collapse text-std-16N-170'>
                    <thead>
                      <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-dns-14N-130 text-solid-gray-600'>
                        <th scope='col' className='w-[calc(56/16*1rem)] px-2 py-2 text-center font-normal'>
                          並び
                        </th>
                        <th scope='col' className='px-3 py-2 font-normal'>
                          書類名
                        </th>
                        <th scope='col' className='w-[calc(80/16*1rem)] px-3 py-2 font-normal'>
                          種別
                        </th>
                        <th scope='col' className='w-[calc(180/16*1rem)] px-3 py-2 font-normal'>
                          状態
                        </th>
                        <th scope='col' className='w-[calc(150/16*1rem)] px-3 py-2 font-normal'>
                          更新
                        </th>
                        <th scope='col' className='w-[calc(220/16*1rem)] px-3 py-2 font-normal'>
                          操作
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((f, index) => {
                        const rows =
                          (f.definition && f.answers)
                            ? answerRows(f.definition.components, f.answers)
                            : [];
                        // 記入と添付は併存できる。ファイルがあるか / 記入済みか を別々に見る。
                        const hasFile = f.file_attached ?? f.fulfillment === 'file';
                        const done = f.status === 'submitted';
                        const isNav = f.kind === 'data';
                        // 実入力欄を持つオンラインフォームがある枠は、添付の有無に関わらず記入も許す。
                        const canFill = f.can_fill_online && !isNav;
                        // 採用中の申請データ（fulfillment 未指定なら添付優先の従来動作）。
                        const adopted: 'form' | 'file' =
                          f.fulfillment === 'file'
                            ? 'file'
                            : f.fulfillment === 'form'
                              ? 'form'
                              : hasFile
                                ? 'file'
                                : 'form';
                        const bothAvailable = Boolean(f.form_submitted) && hasFile;
                        const Icon = isNav ? PiSignpostBold : kindIcon(f.kind);
                        const fillTo = `/patchform/${f.form_id}?app=${encodeURIComponent(application.token)}&item=${encodeURIComponent(f.id)}${fromMy ? '&from=my' : ''}`;
                        return (
                          <tr
                            key={f.id}
                            className={`border-b border-solid-gray-200 last:border-b-0 align-top hover:bg-solid-gray-50 ${
                              isNav ? 'bg-blue-50/40' : ''
                            }`}
                          >
                            <td className='px-2 py-2.5'>
                              <div className='flex flex-col items-center gap-1'>
                                <button
                                  type='button'
                                  aria-label='上へ移動'
                                  className='rounded-4 border border-solid-gray-300 p-1 text-solid-gray-600 hover:bg-solid-gray-100 disabled:opacity-30'
                                  disabled={busy || index === 0}
                                  onClick={() => void onMove(index, 'up')}
                                >
                                  <PiArrowUpBold className='size-4' />
                                </button>
                                <button
                                  type='button'
                                  aria-label='下へ移動'
                                  className='rounded-4 border border-solid-gray-300 p-1 text-solid-gray-600 hover:bg-solid-gray-100 disabled:opacity-30'
                                  disabled={busy || index === items.length - 1}
                                  onClick={() => void onMove(index, 'down')}
                                >
                                  <PiArrowDownBold className='size-4' />
                                </button>
                              </div>
                            </td>
                            <td className='px-3 py-2.5'>
                              <div className='flex items-start gap-2'>
                                <span
                                  className={`relative mt-0.5 inline-flex flex-none ${
                                    isNav ? 'text-blue-900' : 'text-solid-gray-500'
                                  }`}
                                >
                                  <Icon className='size-5' aria-hidden={true} />
                                  {done && (
                                    <PiCheckCircleFill className='absolute -right-1 -bottom-1 size-3 text-green-700' />
                                  )}
                                </span>
                                <div className='min-w-0'>
                                  <div className='flex flex-wrap items-center gap-1.5'>
                                    {canFill || isNav ? (
                                      <Link
                                        to={fillTo}
                                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                                      >
                                        {f.title}
                                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                                      </Link>
                                    ) : (
                                      <span className='text-std-16B-150 text-solid-gray-900'>
                                        {f.title}
                                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                                      </span>
                                    )}
                                    {isNav && (
                                      <span className='rounded-4 border border-blue-900 bg-blue-50 px-1.5 py-0.5 text-dns-14N-130 text-blue-900'>
                                        ナビゲーション
                                      </span>
                                    )}
                                  </div>
                                  {f.template && aid && (
                                    <div>
                                      <button
                                        type='button'
                                        className='text-left text-dns-14N-130 text-blue-900 underline-offset-2 hover:underline'
                                        onClick={() =>
                                          void downloadItemTemplate(
                                            aid,
                                            f.id,
                                            f.template?.filename,
                                          )
                                        }
                                      >
                                        様式ひな型をDL（{f.template.filename}）
                                      </button>
                                    </div>
                                  )}
                                  {rows.length > 0 && (
                                    <details className='mt-0.5 text-dns-14N-130'>
                                      <summary className='cursor-pointer text-solid-gray-700'>
                                        記入内容（{rows.length}項目）
                                      </summary>
                                      <dl className='mt-1 grid gap-1'>
                                        {rows.map((row) => (
                                          <div key={row.id} className='grid gap-0.5'>
                                            <dt className='text-solid-gray-600'>{row.label}</dt>
                                            <dd className='whitespace-pre-wrap text-solid-gray-900'>
                                              {row.value}
                                            </dd>
                                          </div>
                                        ))}
                                      </dl>
                                    </details>
                                  )}
                                </div>
                              </div>
                            </td>
                            <td className='px-3 py-2.5 text-dns-14N-130 text-solid-gray-700'>
                              {isNav ? '案内' : kindLabel[f.kind] || f.kind}
                            </td>
                            <td className='px-3 py-2.5'>
                              <span
                                className={`text-dns-14N-130 ${statusTone[f.status] || 'text-solid-gray-600'}`}
                              >
                                {statusLabel[f.status] || f.status}
                              </span>
                              {hasFile && f.file_name && (
                                <div className='text-dns-14N-130 text-solid-gray-500 break-all'>
                                  {f.file_name}
                                </div>
                              )}
                              {bothAvailable && (
                                <div className='mt-1 flex flex-col gap-0.5'>
                                  <span className='text-dns-14N-130 text-solid-gray-600'>
                                    申請データに採用:
                                  </span>
                                  <div className='inline-flex overflow-hidden rounded-4 border border-solid-gray-400 text-dns-14N-130'>
                                    <button
                                      type='button'
                                      aria-pressed={adopted === 'form'}
                                      disabled={busy}
                                      className={`px-2 py-0.5 ${
                                        adopted === 'form'
                                          ? 'bg-blue-900 text-white'
                                          : 'bg-white text-solid-gray-700 hover:bg-solid-gray-100'
                                      }`}
                                      onClick={() => void onSetSource(f, 'form')}
                                    >
                                      記入
                                    </button>
                                    <button
                                      type='button'
                                      aria-pressed={adopted === 'file'}
                                      disabled={busy}
                                      className={`px-2 py-0.5 ${
                                        adopted === 'file'
                                          ? 'bg-blue-900 text-white'
                                          : 'bg-white text-solid-gray-700 hover:bg-solid-gray-100'
                                      }`}
                                      onClick={() => void onSetSource(f, 'file')}
                                    >
                                      添付
                                    </button>
                                  </div>
                                </div>
                              )}
                            </td>
                            <td className='px-3 py-2.5 text-dns-14N-130 text-solid-gray-500'>
                              {f.submitted_at
                                ? new Date(f.submitted_at).toLocaleString('ja-JP')
                                : '—'}
                            </td>
                            <td className='px-3 py-2.5'>
                              {f.kind !== 'data' ? (
                                <div className='flex flex-wrap gap-2'>
                                  {canFill && (
                                    <Link to={fillTo} className='inline-flex'>
                                      <Button type='button' variant='outline' size='sm'>
                                        {f.form_submitted ? '記入を修正' : 'オンラインで記入'}
                                      </Button>
                                    </Link>
                                  )}
                                  <input
                                    ref={(el) => {
                                      fileInputs.current[f.id] = el;
                                    }}
                                    type='file'
                                    className='hidden'
                                    onChange={(e) => void onPickFile(f, e.target.files?.[0])}
                                  />
                                  {hasFile ? (
                                    <Button
                                      type='button'
                                      variant='outline'
                                      size='sm'
                                      aria-disabled={busy}
                                      onClick={() => void onClearFile(f)}
                                    >
                                      添付を取消
                                    </Button>
                                  ) : (
                                    <Button
                                      type='button'
                                      variant='outline'
                                      size='sm'
                                      aria-disabled={busy}
                                      onClick={() => fileInputs.current[f.id]?.click()}
                                    >
                                      ファイルを添付
                                    </Button>
                                  )}
                                  <Button
                                    type='button'
                                    variant='outline'
                                    size='sm'
                                    aria-disabled={busy}
                                    onClick={() => void onDuplicate(f)}
                                  >
                                    もう1件
                                  </Button>
                                </div>
                              ) : (
                                <span className='text-dns-14N-130 text-solid-gray-400'>—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <Disclosure className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-4 py-3'>
              <DisclosureSummary>
                <span className='text-std-16B-150'>操作方法（クリックで開く）</span>
              </DisclosureSummary>
              <div className='mt-3 flex flex-col gap-5'>
                <PatchformProcedureCoach
                  title='この申請でやること'
                  lead='様式はオンライン記入でも、記入済みファイルの添付でも構いません。足りなければ枠を足せます。'
                  steps={[
                    {
                      id: 'open',
                      label: '未充足の枠を満たす',
                      done: items.length === 0 || items.every((f) => f.status === 'submitted'),
                      hint: '一覧のカードから記入・添付できます。',
                      action: (() => {
                        const next = items.find(
                          (f) =>
                            f.can_fill_online &&
                            f.fulfillment !== 'file' &&
                            (f.status === 'none' || f.status === 'draft'),
                        );
                        return next
                          ? {
                              label: `「${next.title}」を記入する`,
                              to: `/patchform/${next.form_id}?app=${encodeURIComponent(application.token)}&item=${encodeURIComponent(next.id)}${fromMy ? '&from=my' : ''}`,
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
                <div className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 bg-white p-4'>
                  <h3 className='text-std-16B-150'>枠を足す</h3>
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
                </div>
                <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-white p-4'>
                  <h3 className='text-std-16B-150'>書き出し</h3>
                  <div className='flex flex-wrap gap-2'>
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
              </div>
            </Disclosure>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
