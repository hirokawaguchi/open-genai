import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { PatchformSubnav } from './PatchformSubnav';
import { RECEPTION_STATUS_VALUES, type InboxItem, type ReceptionStatus } from './types';
import {
  downloadProcedureExport,
  usePatchformInbox,
  usePatchformProjectActions,
} from './usePatchform';

const statusLabel = (status: string) => (status === 'published' ? '公開中' : '受付終了');

// 申請者側の提出状態（受付からは変更しない、絞り込み用）。
const APPLICANT_STATUS_VALUES = ['未着手', '作業中', '準備完了', '提出済', '取下げ', '完了'];

type SortKey = 'created' | 'updated' | 'status';
type SortDir = 'asc' | 'desc';

const selectClass =
  'rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130';

export const PatchformInboxPage = () => {
  const { procedureId: pathId } = useParams();
  const [params] = useSearchParams();
  const procedureId = pathId || params.get('procedure') || undefined;
  const { items, procedures, inbox, isLoading, loadError, mutate } =
    usePatchformInbox(procedureId);
  const selected = procedures.find((p) => p.id === procedureId);
  const [exporting, setExporting] = useState<'csv' | 'jsonl' | 'aligned' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const {
    remove,
    setReceptionStatus,
    bulkSetReceptionStatus,
    bulkRemove,
    busy,
    error: actionError,
  } = usePatchformProjectActions();

  // 一括対象の選択
  const [checked, setChecked] = useState<Set<string>>(new Set());
  // 絞り込み
  const [recvFilter, setRecvFilter] = useState('');
  const [applicantFilter, setApplicantFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [keyword, setKeyword] = useState('');
  // 並べ替え
  const [sortKey, setSortKey] = useState<SortKey>('created');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  // 一括バーの受付ステータス選択
  const [bulkRecv, setBulkRecv] = useState<ReceptionStatus>('確認中');

  const bundles = useMemo(() => items.filter((it) => it.kind === 'bundle'), [items]);

  const visible = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    const from = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : null;
    const to = dateTo ? new Date(`${dateTo}T23:59:59`).getTime() : null;
    const filtered = bundles.filter((it) => {
      if (recvFilter && (it.reception_status || '未確認') !== recvFilter) return false;
      if (applicantFilter && (it.status || '') !== applicantFilter) return false;
      const created = new Date(it.created_at).getTime();
      if (from != null && created < from) return false;
      if (to != null && created > to) return false;
      if (kw) {
        const hay = `${it.label || ''} ${it.respondent_label || ''}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
    const dir = sortDir === 'asc' ? 1 : -1;
    const stamp = (it: InboxItem, key: SortKey) =>
      key === 'updated' ? it.updated_at || it.created_at : it.created_at;
    filtered.sort((a, b) => {
      if (sortKey === 'status') {
        return (a.status || '').localeCompare(b.status || '', 'ja') * dir;
      }
      const av = new Date(stamp(a, sortKey)).getTime();
      const bv = new Date(stamp(b, sortKey)).getTime();
      return (av - bv) * dir;
    });
    return filtered;
  }, [bundles, recvFilter, applicantFilter, dateFrom, dateTo, keyword, sortKey, sortDir]);

  const visibleIds = visible.map((it) => it.id);
  const selectedIds = visibleIds.filter((id) => checked.has(id));
  const allSelected = visibleIds.length > 0 && selectedIds.length === visibleIds.length;

  const toggleOne = (id: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (allSelected) for (const id of visibleIds) next.delete(id);
      else for (const id of visibleIds) next.add(id);
      return next;
    });

  const onSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir(key === 'status' ? 'asc' : 'desc');
    }
  };
  const sortMark = (key: SortKey) => (sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '');

  const onDelete = async (id: string, label: string) => {
    if (
      !window.confirm(
        `申請「案内番号 ${label}」を完全に削除します。提出済みの回答や添付も消え、元に戻せません。よろしいですか？`,
      )
    )
      return;
    const ok = await remove(id);
    if (ok) {
      setChecked((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      await mutate();
    }
  };

  const onRowReception = async (id: string, value: string) => {
    const res = await setReceptionStatus(id, value);
    if (res) await mutate();
  };

  const onBulkReception = async () => {
    if (selectedIds.length === 0) return;
    const res = await bulkSetReceptionStatus(selectedIds, bulkRecv);
    if (res) await mutate();
  };

  const onBulkDelete = async () => {
    if (selectedIds.length === 0) return;
    if (
      !window.confirm(
        `選択した ${selectedIds.length} 件の申請を完全に削除します。提出済みの回答や添付も消え、元に戻せません。よろしいですか？`,
      )
    )
      return;
    const res = await bulkRemove(selectedIds);
    if (res) {
      setChecked(new Set());
      await mutate();
    }
  };

  const download = async (format: 'csv' | 'jsonl' | 'aligned', ids?: string[]) => {
    if (!selected) return;
    setExporting(format);
    setExportError(null);
    try {
      await downloadProcedureExport(selected.id, format, ids);
    } catch {
      setExportError('この手続きの申請を書き出せませんでした。');
    } finally {
      setExporting(null);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={`申請受付 · ${PATCHFORM_LABEL}`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '申請受付', to: '/patchform/inbox' },
            ...(selected ? [{ label: selected.name }] : []),
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>
            {selected ? selected.name : '申請受付'}
          </h1>
          <PatchformSubnav current='inbox' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            {selected
              ? 'この手続きに受付された申請です。案内番号を開くと、提出済みの回答を見られます。'
              : '公開中、または申請が届いている手続きです。手続きを選ぶと申請一覧を見られます。'}
          </p>
        </div>

        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}

        {selected ? (
          <section className='flex flex-col gap-3'>
            <p className='text-dns-14N-130 text-solid-gray-600'>
              {statusLabel(selected.status)}
              {selected.guide_title ? ` / ${selected.guide_title}` : ''}
              {` / 申請 ${selected.bundle_count} 件`}
            </p>
            <div className='flex flex-wrap gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={exporting != null}
                onClick={() => void download('csv')}
              >
                {exporting === 'csv' ? '書き出し中...' : 'CSVをまとめてダウンロード'}
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={exporting != null}
                onClick={() => void download('jsonl')}
              >
                {exporting === 'jsonl' ? '書き出し中...' : 'JSONLをまとめてダウンロード'}
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={exporting != null}
                title='記入必須の項目だけを申請をまたいで揃えた表です。他システムへ渡す用です。'
                onClick={() => void download('aligned')}
              >
                {exporting === 'aligned' ? '書き出し中...' : '記入必須だけ揃えて書き出す'}
              </Button>
            </div>
            <p className='text-dns-14N-130 text-solid-gray-600'>
              CSV はざっと見る表です。連携契約には使いません。他システムへ渡すときは「記入必須だけ揃えて書き出す」を使ってください。
            </p>
            {exportError && (
              <p className='text-error-1' role='alert'>
                {exportError}
              </p>
            )}

            <h2 className='mt-4 text-std-18B-160'>届いた申請</h2>
            {inbox && (
              <p className='text-dns-14N-130 text-solid-gray-600'>
                全 {bundles.length} 件 / 表示 {visible.length} 件
              </p>
            )}
            {actionError && (
              <p className='text-error-1' role='alert'>
                {actionError}
              </p>
            )}

            {/* 絞り込み */}
            <div className='flex flex-wrap items-end gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-3'>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                受付処理
                <select
                  className={selectClass}
                  value={recvFilter}
                  onChange={(e) => setRecvFilter(e.target.value)}
                >
                  <option value=''>すべて</option>
                  {RECEPTION_STATUS_VALUES.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                申請者状態
                <select
                  className={selectClass}
                  value={applicantFilter}
                  onChange={(e) => setApplicantFilter(e.target.value)}
                >
                  <option value=''>すべて</option>
                  {APPLICANT_STATUS_VALUES.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                受付日（自）
                <input
                  type='date'
                  className={selectClass}
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                />
              </label>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                受付日（至）
                <input
                  type='date'
                  className={selectClass}
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                />
              </label>
              <label className='flex flex-1 flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                キーワード（案内番号・申請者）
                <input
                  type='search'
                  className={selectClass}
                  value={keyword}
                  placeholder='案内番号や申請者で絞り込み'
                  onChange={(e) => setKeyword(e.target.value)}
                />
              </label>
              {(recvFilter || applicantFilter || dateFrom || dateTo || keyword) && (
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => {
                    setRecvFilter('');
                    setApplicantFilter('');
                    setDateFrom('');
                    setDateTo('');
                    setKeyword('');
                  }}
                >
                  絞り込みを解除
                </Button>
              )}
            </div>

            {/* 一括バー */}
            {selectedIds.length > 0 && (
              <div className='flex flex-wrap items-center gap-3 rounded-8 border border-blue-900 bg-blue-50 p-3'>
                <span className='text-dns-14B-130 text-solid-gray-800'>
                  {selectedIds.length} 件を選択中
                </span>
                <div className='flex items-center gap-2'>
                  <select
                    className={selectClass}
                    value={bulkRecv}
                    onChange={(e) => setBulkRecv(e.target.value as ReceptionStatus)}
                    aria-label='受付処理ステータスを選ぶ'
                  >
                    {RECEPTION_STATUS_VALUES.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={busy}
                    onClick={() => void onBulkReception()}
                  >
                    受付処理を一括変更
                  </Button>
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={exporting != null}
                  onClick={() => void download('csv', selectedIds)}
                >
                  選択をCSVでDL
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={exporting != null}
                  onClick={() => void download('jsonl', selectedIds)}
                >
                  選択をJSONLでDL
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={busy}
                  onClick={() => void onBulkDelete()}
                >
                  選択を削除
                </Button>
              </div>
            )}

            {visible.length === 0 ? (
              <p className='text-solid-gray-600'>
                {bundles.length === 0
                  ? 'まだ届いた申請はありません。'
                  : '条件に合う申請はありません。'}
              </p>
            ) : (
              <div className='overflow-x-auto'>
                <table className='w-full min-w-[720px] border-collapse text-dns-14N-130'>
                  <thead>
                    <tr className='border-b border-solid-gray-300 text-left text-solid-gray-600'>
                      <th className='w-10 px-2 py-2'>
                        <input
                          type='checkbox'
                          className='size-6'
                          checked={allSelected}
                          ref={(el) => {
                            if (el)
                              el.indeterminate =
                                selectedIds.length > 0 && !allSelected;
                          }}
                          onChange={toggleAll}
                          aria-label='すべて選択'
                        />
                      </th>
                      <th className='px-2 py-2'>案内番号</th>
                      <th className='px-2 py-2'>申請者</th>
                      <th className='px-2 py-2'>
                        <button
                          type='button'
                          className='font-inherit hover:underline'
                          onClick={() => onSort('status')}
                        >
                          申請者状態{sortMark('status')}
                        </button>
                      </th>
                      <th className='px-2 py-2'>受付処理</th>
                      <th className='px-2 py-2'>提出</th>
                      <th className='px-2 py-2'>
                        <button
                          type='button'
                          className='font-inherit hover:underline'
                          onClick={() => onSort('created')}
                        >
                          受付日時{sortMark('created')}
                        </button>
                      </th>
                      <th className='px-2 py-2'>
                        <button
                          type='button'
                          className='font-inherit hover:underline'
                          onClick={() => onSort('updated')}
                        >
                          更新{sortMark('updated')}
                        </button>
                      </th>
                      <th className='px-2 py-2 text-right'>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((item) => (
                      <tr
                        key={item.id}
                        className='border-b border-solid-gray-200 align-middle'
                      >
                        <td className='px-2 py-2'>
                          <input
                            type='checkbox'
                            className='size-6'
                            checked={checked.has(item.id)}
                            onChange={() => toggleOne(item.id)}
                            aria-label={`案内番号 ${item.label} を選択`}
                          />
                        </td>
                        <td className='px-2 py-2'>
                          <Link
                            to={`/patchform/applications/${item.id}`}
                            className='text-std-14B-140 text-blue-900 underline-offset-2 hover:underline'
                          >
                            {item.label}
                          </Link>
                        </td>
                        <td className='px-2 py-2 text-solid-gray-700'>
                          {item.respondent_label || '-'}
                        </td>
                        <td className='px-2 py-2'>
                          <span className='inline-block rounded-full bg-solid-gray-100 px-2 py-0.5 text-dns-14N-130 text-solid-gray-700'>
                            {item.status || '-'}
                          </span>
                        </td>
                        <td className='px-2 py-2'>
                          <select
                            className={selectClass}
                            value={item.reception_status || '未確認'}
                            aria-disabled={busy}
                            onChange={(e) => void onRowReception(item.id, e.target.value)}
                            aria-label={`案内番号 ${item.label} の受付処理ステータス`}
                          >
                            {RECEPTION_STATUS_VALUES.map((v) => (
                              <option key={v} value={v}>
                                {v}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className='px-2 py-2 text-solid-gray-700'>
                          {item.total != null ? `${item.submitted}/${item.total}` : '-'}
                        </td>
                        <td className='px-2 py-2 text-solid-gray-600'>
                          {new Date(item.created_at).toLocaleString('ja-JP')}
                        </td>
                        <td className='px-2 py-2 text-solid-gray-600'>
                          {item.updated_at
                            ? new Date(item.updated_at).toLocaleString('ja-JP')
                            : '-'}
                        </td>
                        <td className='px-2 py-2 text-right'>
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            aria-disabled={busy}
                            onClick={() => void onDelete(item.id, item.label)}
                          >
                            削除
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <p className='mt-2 text-std-16N-170'>
              <Link to='/patchform/inbox' className='text-blue-900 underline-offset-2 hover:underline'>
                手続き一覧へ戻る
              </Link>
            </p>
          </section>
        ) : (
          <section className='flex flex-col gap-3'>
            <h2 className='text-std-18B-160'>手続き</h2>
            {procedures.length === 0 ? (
              <p className='text-solid-gray-600'>
                公開中の手続きも、届いた申請もありません。先に「手続きを公開」してください。
              </p>
            ) : (
              <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                {procedures.map((item) => (
                  <li key={item.id} className='py-3'>
                    <Link
                      to={`/patchform/inbox/${item.id}`}
                      className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                    >
                      {item.name}
                    </Link>
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      {statusLabel(item.status)}
                      {item.guide_title ? ` / ${item.guide_title}` : ''}
                      {` / 申請 ${item.bundle_count} 件`}
                      {' / '}
                      {new Date(item.updated_at).toLocaleString('ja-JP')}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </LayoutBody>
  );
};
