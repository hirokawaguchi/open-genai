import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { PiMagnifyingGlassBold, PiPlusBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { DOCMAKER_EXAPP_ID } from '@/layout/navItems';
import type { MyApplication } from '../patchform/types';
import { usePatchformRoutes } from '../patchform/routes';
import {
  usePatchformMyApplications,
  usePatchformProcedures,
  usePatchformProjectActions,
} from '../patchform/usePatchform';
import { DOCMAKER_LABEL } from './labels';

const statusStyle = (status: string): string => {
  switch (status) {
    case '提出済':
    case '完了':
      return 'border-green-600 bg-green-50 text-green-800';
    case '準備完了':
      return 'border-amber-600 bg-amber-50 text-amber-800';
    case '作業中':
      return 'border-blue-900 bg-blue-50 text-blue-900';
    case '取下げ':
      return 'border-error-1 bg-red-50 text-error-1';
    default:
      return 'border-solid-gray-420 bg-solid-gray-50 text-solid-gray-700';
  }
};

const STATUS_FILTERS = ['すべて', '未着手', '作業中', '準備完了', '提出済', '完了', '取下げ'] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const fmtDateTime = (v: string): string => (v ? new Date(v).toLocaleString('ja-JP') : '—');

/** 期限が近い/超過なら色を付ける（docmaker の Index に倣う）。 */
const deadlineTone = (deadline: string): string => {
  if (!deadline) return 'text-solid-gray-600';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(`${deadline}T00:00:00`);
  const diff = (d.getTime() - today.getTime()) / 86400000;
  if (diff < 0) return 'text-error-1 font-bold';
  if (diff <= 7) return 'text-orange-700 font-bold';
  return 'text-solid-gray-800';
};

/**
 * docmaker（マイ手続き）：庁内・自分が所有するプロジェクトの一覧。
 * 「フォーム」アプリ（作成・公開・受付）とは別アプリとして分離している。
 * 表形式のエクスプローラー風一覧で、担当・期限・次回更新日を管理できる。
 * 「始める」を押すと作成ウィザードが起動し、案内に答えると提出書類一覧が育つ。
 */
export const DocmakerPage = () => {
  const navigate = useNavigate();
  const routes = usePatchformRoutes();
  const { applications, isLoading, loadError, mutate } = usePatchformMyApplications();
  const { procedures } = usePatchformProcedures();
  const { setStatus, updateMeta, remove, busy, error, setError } =
    usePatchformProjectActions();
  const [pick, setPick] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('すべて');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ assignee: string; deadline: string; next: string }>({
    assignee: '',
    deadline: '',
    next: '',
  });
  const published = procedures.filter((p) => p.status === 'published');

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return applications.filter((a) => {
      if (statusFilter !== 'すべて' && a.status.effective !== statusFilter) return false;
      if (!q) return true;
      return (
        a.title.toLowerCase().includes(q) ||
        a.procedure_name.toLowerCase().includes(q) ||
        (a.assignee || '').toLowerCase().includes(q)
      );
    });
  }, [applications, query, statusFilter]);

  const onStart = () => {
    if (!pick) return;
    setError(null);
    navigate(routes.wizard(pick));
  };

  const onSetStatus = async (id: string, status: string) => {
    const updated = await setStatus(id, status);
    if (updated) await mutate();
  };

  const onDelete = async (a: MyApplication) => {
    if (
      !window.confirm(
        `「${a.title}」を完全に削除します。記入内容や添付も消え、元に戻せません。よろしいですか？`,
      )
    )
      return;
    const ok = await remove(a.id);
    if (ok) await mutate();
  };

  const onRename = async (a: MyApplication) => {
    const next = window.prompt('この手続きの名前', a.title);
    if (next == null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === a.title) return;
    const updated = await updateMeta(a.id, { title: trimmed });
    if (updated) await mutate();
  };

  const startEdit = (a: MyApplication) => {
    setEditingId(a.id);
    setDraft({
      assignee: a.assignee || '',
      deadline: a.deadline || '',
      next: a.next_action_date || '',
    });
  };

  const saveEdit = async (id: string) => {
    const updated = await updateMeta(id, {
      assignee: draft.assignee,
      deadline: draft.deadline,
      next_action_date: draft.next,
    });
    if (updated) {
      setEditingId(null);
      await mutate();
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={DOCMAKER_LABEL} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={DOCMAKER_EXAPP_ID}
          enabled={routes.mode === 'internal'}
          fallbackTitle={routes.myListLabel}
          fallbackDescription='自分の手続き（案件）を一覧で管理します。手続きを選んで始めると、案内に答えるだけで提出書類一覧ができ、記入や添付を少しずつ進められます。'
          breadcrumbItems={[...routes.homeCrumbs, { label: routes.myListLabel }]}
        />

        <section className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
          <h2 className='flex items-center gap-2 text-std-18B-160'>
            <PiPlusBold className='size-5' />
            新しい手続きを始める
          </h2>
          {published.length === 0 ? (
            <p className='text-std-16N-170 text-solid-gray-700'>
              公開中の手続きがありません。
              {routes.procedures && (
                <Link
                  to={routes.procedures}
                  className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                >
                  手続きを公開する
                </Link>
              )}
            </p>
          ) : (
            <div className='flex flex-wrap items-center gap-2'>
              <label className='text-std-16N-170 text-solid-gray-700' htmlFor='dm-pick'>
                手続きを選ぶ
              </label>
              <select
                id='dm-pick'
                className='rounded-4 border border-solid-gray-420 px-2 py-1.5 text-std-16N-170'
                value={pick}
                onChange={(e) => setPick(e.target.value)}
              >
                <option value=''>選択してください</option>
                {published.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <Button
                type='button'
                variant='solid-fill'
                size='sm'
                aria-disabled={busy || !pick}
                onClick={onStart}
              >
                始める
              </Button>
            </div>
          )}
          {error && (
            <p className='text-dns-14N-130 text-error-1' role='alert'>
              {error}
            </p>
          )}
        </section>

        <section className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <h2 className='text-std-18B-160'>進行中・過去の手続き</h2>
            <div className='relative'>
              <PiMagnifyingGlassBold className='pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-solid-gray-500' />
              <input
                type='search'
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder='案件名・手続き・担当で検索'
                className='w-64 rounded-4 border border-solid-gray-420 py-1.5 pl-8 pr-3 text-std-16N-170'
              />
            </div>
          </div>

          <div className='flex flex-wrap gap-2'>
            {STATUS_FILTERS.map((f) => (
              <button
                key={f}
                type='button'
                onClick={() => setStatusFilter(f)}
                className={`rounded-full border px-3 py-1 text-dns-14N-130 ${
                  statusFilter === f
                    ? 'border-blue-900 bg-blue-50 text-blue-900'
                    : 'border-solid-gray-420 bg-white text-solid-gray-700 hover:bg-solid-gray-50'
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          {isLoading ? (
            <p className='text-solid-gray-600'>読み込み中...</p>
          ) : loadError ? (
            <p className='text-error-1' role='alert'>
              {loadError}
            </p>
          ) : applications.length === 0 ? (
            <p className='text-solid-gray-600'>
              まだ手続きがありません。上の「新しい手続きを始める」から始めてください。
            </p>
          ) : rows.length === 0 ? (
            <p className='text-solid-gray-600'>条件に合う手続きがありません。</p>
          ) : (
            <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
              <table className='w-full border-collapse text-std-16N-170'>
                <thead>
                  <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-dns-14N-130 text-solid-gray-600'>
                    <th className='px-3 py-2 font-medium'>案件名</th>
                    <th className='px-3 py-2 font-medium'>状態</th>
                    <th className='px-3 py-2 font-medium'>担当</th>
                    <th className='px-3 py-2 font-medium'>期限</th>
                    <th className='px-3 py-2 font-medium'>次回更新日</th>
                    <th className='px-3 py-2 font-medium'>書類</th>
                    <th className='px-3 py-2 font-medium'>更新</th>
                    <th className='px-3 py-2 font-medium'>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => {
                    const status = a.status.effective;
                    const overridden = Boolean(a.status.override);
                    const editing = editingId === a.id;
                    return (
                      <tr
                        key={a.id}
                        className='border-b border-solid-gray-200 last:border-b-0 align-top hover:bg-solid-gray-50'
                      >
                        <td className='px-3 py-2'>
                          <Link
                            to={routes.application(a.id)}
                            className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                          >
                            {a.title}
                          </Link>
                          <p className='text-dns-14N-130 text-solid-gray-500'>{a.procedure_name}</p>
                        </td>
                        <td className='px-3 py-2'>
                          <span
                            className={`inline-block whitespace-nowrap rounded-4 border px-2 py-0.5 text-dns-14N-130 ${statusStyle(status)}`}
                          >
                            {status}
                          </span>
                        </td>
                        <td className='px-3 py-2'>
                          {editing ? (
                            <input
                              type='text'
                              value={draft.assignee}
                              onChange={(e) =>
                                setDraft((p) => ({ ...p, assignee: e.target.value }))
                              }
                              className='w-28 rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130'
                              placeholder='担当者'
                            />
                          ) : (
                            <span className='text-solid-gray-800'>{a.assignee || '—'}</span>
                          )}
                        </td>
                        <td className='px-3 py-2'>
                          {editing ? (
                            <input
                              type='date'
                              value={draft.deadline}
                              onChange={(e) =>
                                setDraft((p) => ({ ...p, deadline: e.target.value }))
                              }
                              className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130'
                            />
                          ) : (
                            <span className={`whitespace-nowrap text-dns-14N-130 ${deadlineTone(a.deadline)}`}>
                              {a.deadline || '—'}
                            </span>
                          )}
                        </td>
                        <td className='px-3 py-2'>
                          {editing ? (
                            <input
                              type='date'
                              value={draft.next}
                              onChange={(e) => setDraft((p) => ({ ...p, next: e.target.value }))}
                              className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130'
                            />
                          ) : (
                            <span className='whitespace-nowrap text-dns-14N-130 text-solid-gray-800'>
                              {a.next_action_date || '—'}
                            </span>
                          )}
                        </td>
                        <td className='px-3 py-2 whitespace-nowrap text-dns-14N-130 text-solid-gray-700'>
                          {a.total > 0 ? `${a.done}/${a.total}` : '—'}
                        </td>
                        <td className='px-3 py-2 whitespace-nowrap text-dns-14N-130 text-solid-gray-600'>
                          {fmtDateTime(a.updated_at)}
                        </td>
                        <td className='px-3 py-2'>
                          {editing ? (
                            <div className='flex flex-wrap gap-1'>
                              <button
                                type='button'
                                className='rounded-4 border border-blue-900 bg-blue-50 px-2 py-1 text-dns-14N-130 text-blue-900'
                                aria-disabled={busy}
                                onClick={() => void saveEdit(a.id)}
                              >
                                保存
                              </button>
                              <button
                                type='button'
                                className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                                onClick={() => setEditingId(null)}
                              >
                                取消
                              </button>
                            </div>
                          ) : (
                            <div className='flex flex-wrap gap-1'>
                              <button
                                type='button'
                                className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                                onClick={() => startEdit(a)}
                              >
                                編集
                              </button>
                              <button
                                type='button'
                                className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                                onClick={() => void onRename(a)}
                              >
                                改名
                              </button>
                              {overridden ? (
                                <button
                                  type='button'
                                  className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                                  aria-disabled={busy}
                                  onClick={() => void onSetStatus(a.id, '')}
                                >
                                  {status === '提出済'
                                    ? '提出を取下げ'
                                    : status === '取下げ'
                                      ? '取下げを解除'
                                      : status === '完了'
                                        ? '完了を取消'
                                        : '状態を戻す'}
                                </button>
                              ) : (
                                <button
                                  type='button'
                                  className='rounded-4 border border-error-1 px-2 py-1 text-dns-14N-130 text-error-1'
                                  aria-disabled={busy}
                                  onClick={() => void onSetStatus(a.id, '取下げ')}
                                >
                                  取下げ
                                </button>
                              )}
                              <button
                                type='button'
                                className='rounded-4 border border-error-1 bg-red-50 px-2 py-1 text-dns-14N-130 text-error-1'
                                aria-disabled={busy}
                                onClick={() => void onDelete(a)}
                              >
                                削除
                              </button>
                            </div>
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
      </div>
    </LayoutBody>
  );
};
