import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useSWRConfig } from 'swr';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { PatchformSubnav } from './PatchformSubnav';
import type { LedgerRow } from './types';
import {
  usePatchformLedger,
  usePatchformLedgerActions,
  usePatchformLedgerRow,
  usePatchformProcedure,
} from './usePatchform';

const selectClass = 'rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-16N-130';

const caseLabel = (item: LedgerRow) => {
  for (const block of item.snapshot.answers || []) {
    for (const line of block.lines || []) {
      if (typeof line !== 'string' && line.label === '氏名' && line.value) return line.value;
    }
  }
  for (const block of item.snapshot.answers || []) {
    for (const line of block.lines || []) {
      if (typeof line !== 'string' && line.label && line.value) return line.value;
    }
  }
  return item.confirmed_at ? new Date(item.confirmed_at).toLocaleString('ja-JP') : '申請';
};

export const PatchformLedgerPage = () => {
  const { rowId, procedureId } = useParams();
  const { mutate: mutateCache } = useSWRConfig();
  const { rows, isLoading, loadError, mutate: mutateList } = usePatchformLedger(procedureId);
  const { row, isLoading: rowLoading, loadError: rowError, mutate } = usePatchformLedgerRow(rowId);
  const { save, busy, error } = usePatchformLedgerActions();
  const [assignee, setAssignee] = useState('');
  const [status, setStatus] = useState('');
  const [comment, setComment] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState('');
  const [bulkAssignee, setBulkAssignee] = useState('');
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const [bookKeyword, setBookKeyword] = useState('');
  const { procedure } = usePatchformProcedure(procedureId);
  const statuses = procedure?.handling?.statuses?.length
    ? procedure.handling.statuses
    : ['受理', '処理中', '完了'];

  useEffect(() => {
    if (!row) return;
    setAssignee(row.assignee || '');
    setStatus(row.status || '');
    setComment(row.comment || '');
  }, [row]);

  const onSave = async () => {
    if (!rowId) return;
    const updated = await save(rowId, { assignee, status, comment });
    if (updated) {
      await mutate(updated, { revalidate: false });
      await mutateList();
      await mutateCache(
        (key) => typeof key === 'string' && key.startsWith('patchform/ledger'),
      );
    }
  };

  const visibleRows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    const from = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : null;
    const to = dateTo ? new Date(`${dateTo}T23:59:59`).getTime() : null;
    return rows.filter((item) => {
      if (statusFilter && item.status !== statusFilter) return false;
      const confirmed = new Date(item.confirmed_at).getTime();
      if (from != null && confirmed < from) return false;
      if (to != null && confirmed > to) return false;
      if (kw && !`${caseLabel(item)} ${item.assignee}`.toLowerCase().includes(kw)) return false;
      return true;
    });
  }, [rows, statusFilter, keyword, dateFrom, dateTo]);
  const visibleIds = visibleRows.map((item) => item.id);
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

  const onBulk = async () => {
    if (selectedIds.length === 0) return;
    if (!bulkStatus && !bulkAssignee.trim()) {
      setBulkNote('状態か担当を指定してください。');
      return;
    }
    setBulkNote(null);
    let failed = 0;
    for (const id of selectedIds) {
      const updated = await save(id, {
        ...(bulkStatus ? { status: bulkStatus } : {}),
        ...(bulkAssignee.trim() ? { assignee: bulkAssignee.trim() } : {}),
      });
      if (!updated) failed += 1;
    }
    setChecked(new Set());
    setBulkNote(
      failed
        ? `${selectedIds.length - failed} 件を更新し、${failed} 件は更新できませんでした。`
        : `${selectedIds.length} 件を更新しました。`,
    );
    await mutateList();
  };

  const books = useMemo(() => {
    const grouped = new Map<string, { id: string; name: string; count: number; updated: string }>();
    for (const item of rows) {
      const updated = item.updated_at || item.confirmed_at || '';
      const current = grouped.get(item.procedure_id);
      if (!current) {
        grouped.set(item.procedure_id, {
          id: item.procedure_id,
          name: item.procedure_name,
          count: 1,
          updated,
        });
      } else {
        current.count += 1;
        if (updated > current.updated) current.updated = updated;
      }
    }
    return [...grouped.values()];
  }, [rows]);
  const procedureName = row?.procedure_name || rows[0]?.procedure_name || '台帳';

  return (
    <LayoutBody>
      <PageTitle title={`台帳 · ${PATCHFORM_LABEL}`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '台帳', to: procedureId || rowId ? '/patchform/ledger' : undefined },
            ...(procedureId || row
              ? [
                  {
                    label: procedureName,
                    to: row
                      ? `/patchform/ledger/procedure/${row.procedure_id}`
                      : undefined,
                  },
                ]
              : []),
            ...(row ? [{ label: caseLabel(row) }] : []),
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>
            {row ? caseLabel(row) : procedureId ? procedureName : '台帳'}
          </h1>
          <PatchformSubnav current='ledger' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            {row
              ? 'この1件の担当、状態、コメントを進めます。確定した内容は下にあります。'
              : procedureId
                ? 'この台帳に入っている申請です。行を開くと、担当や確定した内容を見られます。'
                : '手続きごとに台帳があります。開くと、その手続きで受理した申請が並びます。'}
          </p>
        </div>
        {(loadError || rowError) && (
          <p className='text-error-1' role='alert'>
            {loadError || rowError}
          </p>
        )}
        {!rowId &&
          (isLoading ? (
            <p>読み込み中...</p>
          ) : procedureId ? (
            rows.length === 0 ? (
              <p className='text-std-16N-170'>この台帳にはまだ申請がありません。</p>
            ) : (
              <section className='flex flex-col gap-3'>
                <p className='text-std-16N-170 text-solid-gray-800'>
                  受付で確定した申請が、この台帳に残ります。
                  {procedure?.can_edit ? (
                    <>
                      {' '}
                      <Link
                        to={`/patchform/procedures/${procedureId}`}
                        className='text-blue-900 underline-offset-2 hover:underline'
                      >
                        行き先は手続きで決めます
                      </Link>
                    </>
                  ) : null}
                </p>
                <p className='text-dns-16N-130 text-solid-gray-600'>
                  全 {rows.length} 件 / 表示 {visibleRows.length} 件
                </p>
                <div className='flex flex-wrap items-end gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-3'>
                  <label className='flex flex-col gap-1 text-dns-16N-130 text-solid-gray-700'>
                    状態
                    <select
                      className={selectClass}
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                    >
                      <option value=''>すべて</option>
                      {statuses.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className='flex flex-col gap-1 text-dns-16N-130 text-solid-gray-700'>
                    確定日（自）
                    <input
                      type='date'
                      className={selectClass}
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                    />
                  </label>
                  <label className='flex flex-col gap-1 text-dns-16N-130 text-solid-gray-700'>
                    確定日（至）
                    <input
                      type='date'
                      className={selectClass}
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                    />
                  </label>
                  <label className='flex flex-1 flex-col gap-1 text-dns-16N-130 text-solid-gray-700'>
                    キーワード（申請・担当）
                    <input
                      type='search'
                      className={selectClass}
                      value={keyword}
                      placeholder='氏名や担当で絞り込み'
                      onChange={(e) => setKeyword(e.target.value)}
                    />
                  </label>
                  {(statusFilter || dateFrom || dateTo || keyword) && (
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      onClick={() => {
                        setStatusFilter('');
                        setDateFrom('');
                        setDateTo('');
                        setKeyword('');
                      }}
                    >
                      絞り込みを解除
                    </Button>
                  )}
                </div>
                <div
                  className={`flex flex-wrap items-center gap-3 rounded-8 border p-3 ${
                    selectedIds.length > 0
                      ? 'border-blue-900 bg-blue-50'
                      : 'border-solid-gray-300 bg-solid-gray-50'
                  }`}
                >
                  <span className='text-dns-16B-130 text-solid-gray-800'>
                    {selectedIds.length > 0
                      ? `${selectedIds.length} 件を選択中`
                      : '行を選ぶと、まとめて処理できます'}
                  </span>
                  <label className='flex items-center gap-2 text-dns-16N-130'>
                    状態
                    <select
                      className={selectClass}
                      value={bulkStatus}
                      onChange={(e) => setBulkStatus(e.target.value)}
                      aria-label='一括で変える状態'
                    >
                      <option value=''>状態は変えない</option>
                      {statuses.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className='flex items-center gap-2 text-dns-16N-130'>
                    担当
                    <input
                      className={selectClass}
                      value={bulkAssignee}
                      placeholder='空なら担当は変えない'
                      onChange={(e) => setBulkAssignee(e.target.value)}
                      aria-label='一括で変える担当'
                    />
                  </label>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={busy || selectedIds.length === 0}
                    onClick={() => void onBulk()}
                  >
                    選択を更新
                  </Button>
                </div>
                {bulkNote && <p className='text-dns-16N-130 text-solid-gray-700'>{bulkNote}</p>}
                {error && (
                  <p className='text-error-1' role='alert'>
                    {error}
                  </p>
                )}
                {visibleRows.length === 0 ? (
                  <p className='text-solid-gray-600'>条件に合う申請はありません。</p>
                ) : (
                  <div className='overflow-x-auto'>
                    <table className='w-full min-w-[720px] border-collapse text-dns-16N-130'>
                      <thead>
                        <tr className='border-b border-solid-gray-300 text-left text-solid-gray-600'>
                          <th className='w-10 px-2 py-2 font-normal'>
                            <input
                              type='checkbox'
                              className='size-6'
                              checked={allSelected}
                              onChange={toggleAll}
                              aria-label='すべて選択'
                            />
                          </th>
                          <th className='px-2 py-2 font-normal'>申請</th>
                          <th className='px-2 py-2 font-normal'>状態</th>
                          <th className='px-2 py-2 font-normal'>担当</th>
                          <th className='px-2 py-2 font-normal'>確定日時</th>
                          <th className='px-2 py-2 font-normal'>更新</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleRows.map((item) => (
                          <tr key={item.id} className='border-b border-solid-gray-200 align-middle'>
                            <td className='px-2 py-2'>
                              <input
                                type='checkbox'
                                className='size-6'
                                checked={checked.has(item.id)}
                                onChange={() => toggleOne(item.id)}
                                aria-label={`${caseLabel(item)} を選択`}
                              />
                            </td>
                            <td className='px-2 py-2'>
                              <Link
                                to={`/patchform/ledger/${item.id}`}
                                className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                              >
                                {caseLabel(item)}
                              </Link>
                            </td>
                            <td className='px-2 py-2'>
                              <span className='inline-block rounded-full bg-solid-gray-100 px-2 py-0.5 text-solid-gray-700'>
                                {item.status || '—'}
                              </span>
                            </td>
                            <td className='px-2 py-2 text-solid-gray-700'>{item.assignee || '—'}</td>
                            <td className='px-2 py-2 text-solid-gray-600'>
                              {item.confirmed_at
                                ? new Date(item.confirmed_at).toLocaleString('ja-JP')
                                : '—'}
                            </td>
                            <td className='px-2 py-2 text-solid-gray-600'>
                              {item.updated_at
                                ? new Date(item.updated_at).toLocaleString('ja-JP')
                                : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )
          ) : books.length === 0 ? (
            <p className='text-std-16N-170'>まだ台帳はありません。受付の経路で確定すると現れます。</p>
          ) : (
            <section className='flex flex-col gap-3'>
              <p className='text-dns-16N-130 text-solid-gray-600'>
                全 {books.length} 件 / 表示{' '}
                {
                  books.filter((book) =>
                    book.name.toLowerCase().includes(bookKeyword.trim().toLowerCase()),
                  ).length
                }{' '}
                件
              </p>
              <div className='flex flex-wrap items-end gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-3'>
                <label className='flex flex-1 flex-col gap-1 text-dns-16N-130 text-solid-gray-700'>
                  キーワード
                  <input
                    type='search'
                    className={selectClass}
                    value={bookKeyword}
                    placeholder='台帳の名前で絞り込み'
                    onChange={(e) => setBookKeyword(e.target.value)}
                  />
                </label>
                {bookKeyword && (
                  <Button type='button' variant='outline' size='sm' onClick={() => setBookKeyword('')}>
                    絞り込みを解除
                  </Button>
                )}
              </div>
              <div className='flex flex-wrap items-center gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-3'>
                <span className='text-dns-16B-130 text-solid-gray-800'>
                  台帳を開くと、中の申請をまとめて処理できます。
                </span>
              </div>
              <div className='overflow-x-auto'>
                <table className='w-full min-w-[720px] border-collapse text-dns-16N-130'>
                  <thead>
                    <tr className='border-b border-solid-gray-300 text-left text-solid-gray-600'>
                      <th className='px-2 py-2 font-normal'>台帳</th>
                      <th className='px-2 py-2 font-normal'>件数</th>
                      <th className='px-2 py-2 font-normal'>更新</th>
                    </tr>
                  </thead>
                  <tbody>
                    {books
                      .filter((book) =>
                        book.name.toLowerCase().includes(bookKeyword.trim().toLowerCase()),
                      )
                      .map((book) => (
                        <tr key={book.id} className='border-b border-solid-gray-200 align-middle'>
                          <td className='px-2 py-2'>
                            <Link
                              to={`/patchform/ledger/procedure/${book.id}`}
                              className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                            >
                              {book.name}
                            </Link>
                          </td>
                          <td className='px-2 py-2 text-solid-gray-700'>{book.count}</td>
                          <td className='px-2 py-2 text-solid-gray-600'>
                            {book.updated ? new Date(book.updated).toLocaleString('ja-JP') : '—'}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        {rowId && rowLoading && <p>読み込み中...</p>}
        {row && (
          <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-420 bg-white p-4'>
            <p className='text-dns-16N-130 text-solid-gray-600'>
              確定 {new Date(row.confirmed_at).toLocaleString('ja-JP')}
            </p>
            <label className='flex flex-col gap-1 text-dns-16N-130'>
              担当
              <input
                className='rounded-4 border border-solid-gray-420 px-3 py-2'
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
              />
            </label>
            <label className='flex flex-col gap-1 text-dns-16N-130'>
              状態
              <input
                className='rounded-4 border border-solid-gray-420 px-3 py-2'
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              />
            </label>
            <label className='flex flex-col gap-1 text-dns-16N-130'>
              コメント
              <textarea
                className='min-h-20 rounded-4 border border-solid-gray-420 px-3 py-2'
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </label>
            <div>
              <Button type='button' variant='outline' size='sm' disabled={busy} onClick={() => void onSave()}>
                台帳を保存する
              </Button>
            </div>
            {error && (
              <p className='text-error-1' role='alert'>
                {error}
              </p>
            )}
            <div>
              <h3 className='text-std-16B-150'>確定した内容</h3>
              {(row.snapshot.answers || []).map((block) => (
                <div key={block.title} className='mt-3'>
                  <p className='text-std-16B-150'>{block.title}</p>
                  <dl className='mt-1 flex flex-col gap-2'>
                    {(block.lines || []).map((line, index) =>
                      typeof line === 'string' ? (
                        <div key={`${block.title}-${index}`} className='text-std-16N-170'>
                          {line}
                        </div>
                      ) : (
                        <div key={`${block.title}-${line.label}-${index}`}>
                          <dt className='text-dns-16N-130 text-solid-gray-600'>{line.label}</dt>
                          <dd className='text-std-16N-170'>{line.value}</dd>
                        </div>
                      ),
                    )}
                  </dl>
                </div>
              ))}
              {(row.snapshot.files || []).length > 0 && (
                <ul className='mt-2 list-disc pl-5 text-std-16N-170'>
                  {row.snapshot.files?.map((file) => (
                    <li key={file.file_id}>
                      {file.copied ? (
                        <a
                          className='text-blue-900 underline-offset-2 hover:underline'
                          href={`/api/patchform/ledger/${row.id}/files/${file.file_id}`}
                        >
                          {file.name}
                        </a>
                      ) : (
                        file.name
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3 className='text-std-16B-150'>履歴</h3>
              <ul className='mt-1 flex flex-col gap-1 text-dns-16N-130 text-solid-gray-700'>
                {row.events.map((event) => (
                  <li key={event.id}>
                    {event.action}
                    {event.detail ? `（${event.detail}）` : ''}{' '}
                    {new Date(event.created_at).toLocaleString('ja-JP')}
                  </li>
                ))}
              </ul>
            </div>
            <p className='flex flex-wrap gap-4'>
              <Link
                to={`/patchform/ledger/procedure/${row.procedure_id}`}
                className='text-blue-900 underline-offset-2 hover:underline'
              >
                この台帳の一覧へ戻る
              </Link>
              <Link
                to={`/patchform/applications/${row.application_id}`}
                className='text-blue-900 underline-offset-2 hover:underline'
              >
                申請を開く
              </Link>
            </p>
          </section>
        )}
      </div>
    </LayoutBody>
  );
};
