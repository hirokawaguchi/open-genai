import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { PiListBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_EXAPP_ID } from '@/layout/navItems';
import { FormCreateWizard } from './FormCreateWizard';
import { FormTagList } from './FormTagsField';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformPaneTabs } from './PatchformPaneTabs';
import { PatchformSubnav } from './PatchformSubnav';
import {
  downloadFormPortable,
  readExportBundleFile,
  usePatchformActions,
  usePatchformConfig,
  usePatchformList,
  usePatchformTagActions,
  usePatchformTags,
} from './usePatchform';

const workLabel = (locked?: boolean, workStatus?: string | null) =>
  locked || workStatus === 'ready' ? '作成完了' : '作成中';

/**
 * フォーム専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["patchform"] 未起動時は有効化手順を案内する。
 */
export const PatchformPage = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const fromGuideLink = searchParams.get('intent') === 'guide';
  const kind: 'application' | 'navigation' =
    searchParams.get('kind') === 'navigation' || fromGuideLink ? 'navigation' : 'application';
  const { config, isLoading: configLoading, unavailable } = usePatchformConfig();
  const { forms, isLoading, loadError, mutate } = usePatchformList();
  const { tags: tagUsage, mutate: mutateTags } = usePatchformTags();
  const {
    rename: renameTag,
    remove: removeTag,
    busy: tagBusy,
    error: tagActionError,
  } = usePatchformTagActions();
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const {
    setStatusMany,
    applyTagsMany,
    removeMany,
    importForm,
    duplicate: duplicateForm,
    submitting,
  } = usePatchformActions();
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null);
  const asGuide = kind === 'navigation';
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardKind, setWizardKind] = useState<'application' | 'navigation'>(kind);
  const [statusFilter, setStatusFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  const [bulkAction, setBulkAction] = useState('');
  const [tagTargets, setTagTargets] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState('');
  const isNavForm = (f: { tags?: string[] | null }) => (f.tags || []).includes(NAVIGATION_TAG);
  const appForms = forms.filter((f) => !isNavForm(f));
  const navForms = forms.filter((f) => isNavForm(f));
  const kindForms = kind === 'navigation' ? navForms : appForms;
  const appActiveCount = appForms.filter((f) => f.status !== 'archived').length;
  const navActiveCount = navForms.filter((f) => f.status !== 'archived').length;
  const knownTags = [...new Set(kindForms.flatMap((f) => f.tags || []))]
    .filter((t) => t !== NAVIGATION_TAG)
    .sort();
  const activeCount = kindForms.filter((f) => f.status !== 'archived').length;
  const trashCount = kindForms.filter((f) => f.status === 'archived').length;
  const trashView = statusFilter === 'trash';

  const refreshAfterTagChange = async () => {
    await Promise.all([mutate(), mutateTags()]);
  };

  const onRenameTag = async (tag: string) => {
    const next = window.prompt(`タグ「${tag}」の新しい名前`, tag);
    if (next == null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === tag) return;
    const changed = await renameTag(tag, trimmed);
    if (changed != null) {
      setTagFilter((cur) => (cur === tag ? '' : cur));
      await refreshAfterTagChange();
    }
  };

  const onDeleteTag = async (tag: string, count: number) => {
    if (
      !window.confirm(
        `タグ「${tag}」を ${count} 件のフォームからすべて外します（ゴミ箱内のフォームも対象）。フォーム自体は消えません。よろしいですか？`,
      )
    )
      return;
    const changed = await removeTag(tag);
    if (changed != null) {
      setTagFilter((cur) => (cur === tag ? '' : cur));
      await refreshAfterTagChange();
    }
  };

  const visibleForms = forms.filter((f) => {
    if ((kind === 'navigation') !== isNavForm(f)) return false;
    if (trashView) return f.status === 'archived';
    if (f.status === 'archived') return false;
    if (statusFilter) {
      const ready = Boolean(f.locked || f.work_status === 'ready');
      if (statusFilter === 'ready' ? !ready : ready) return false;
    }
    if (tagFilter && !(f.tags || []).includes(tagFilter)) return false;
    return true;
  });
  // 一括対象は編集権限のある行（状態変更・タグ・ゴミ箱移動は編集者以上）
  const selectableVisible = visibleForms.filter((f) => f.can_edit);
  const selectedCount = selectableVisible.filter((f) => selected.has(f.id)).length;
  const allSelected = selectableVisible.length > 0 && selectedCount === selectableVisible.length;
  const selectedForms = selectableVisible.filter((f) => selected.has(f.id));
  const titleOf = (id: string) => forms.find((f) => f.id === id)?.title || id;

  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        for (const f of selectableVisible) next.delete(f.id);
      } else {
        for (const f of selectableVisible) next.add(f.id);
      }
      return next;
    });

  const selectedTags = [...new Set(selectedForms.flatMap((f) => f.tags || []))].sort();

  const resetBulk = () => {
    setBulkAction('');
    setTagTargets([]);
    setTagDraft('');
  };

  const chooseBulkAction = (action: string) => {
    setBulkAction(action);
    setTagTargets([]);
    setTagDraft('');
  };

  const addTagTarget = (raw: string) => {
    const tag = raw.trim();
    if (!tag || tag.length > 30 || tagTargets.includes(tag)) {
      setTagDraft('');
      return;
    }
    setTagTargets((prev) => [...prev, tag]);
    setTagDraft('');
  };

  const toggleTagTarget = (tag: string) =>
    setTagTargets((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );

  const selectFilter = (id: string) => {
    setStatusFilter(id);
    setSelected(new Set());
    setBulkResult(null);
    resetBulk();
  };

  const summarize = (
    results: { id: string; ok: boolean; error?: string }[],
    okLabel: string,
  ) => {
    const ok = results.filter((r) => r.ok);
    const ng = results.filter((r) => !r.ok);
    const parts: string[] = [];
    if (ok.length) parts.push(`${ok.length} 件を${okLabel}。`);
    if (ng.length) {
      parts.push(
        `${ng.length} 件は変更できませんでした（` +
          ng.map((r) => `「${titleOf(r.id)}」: ${r.error}`).join(' / ') +
          '）。',
      );
    }
    setBulkResult(parts.join(''));
  };

  const runBulk = async () => {
    const ids = selectedForms.map((f) => f.id);
    if (ids.length === 0 || !bulkAction) return;
    setBulkResult(null);
    if (bulkAction === 'ready') {
      summarize(await setStatusMany(ids, 'draft', { locked: true }), '作成完了にしました');
    } else if (bulkAction === 'editing') {
      summarize(await setStatusMany(ids, 'draft', { locked: false }), '作成に戻しました');
    } else if (bulkAction === 'archive') {
      if (
        !window.confirm(
          `選択した ${ids.length} 件をゴミ箱へ移します。一覧から隠れますが、あとでゴミ箱から復元できます。`,
        )
      )
        return;
      summarize(await setStatusMany(ids, 'archived'), 'ゴミ箱へ移しました');
    } else if (bulkAction === 'tag_add' || bulkAction === 'tag_remove') {
      const targets = [...tagTargets];
      if (tagDraft.trim() && bulkAction === 'tag_add') targets.push(tagDraft.trim());
      const uniqueTargets = [...new Set(targets)];
      if (uniqueTargets.length === 0) return;
      const entries = selectedForms.map((f) => {
        const current = f.tags || [];
        const tags =
          bulkAction === 'tag_add'
            ? [...new Set([...current, ...uniqueTargets])]
            : current.filter((t) => !uniqueTargets.includes(t));
        return { id: f.id, tags };
      });
      summarize(
        await applyTagsMany(entries),
        bulkAction === 'tag_add' ? 'タグを付けました' : 'タグを外しました',
      );
    }
    await mutate();
    setSelected(new Set());
    resetBulk();
  };

  const onRestore = async () => {
    const ids = selectedForms.map((f) => f.id);
    if (ids.length === 0) return;
    setBulkResult(null);
    summarize(await setStatusMany(ids, 'draft', { locked: false }), '復元しました');
    await mutate();
    setSelected(new Set());
  };

  const onPurge = async () => {
    const ids = selectedForms.map((f) => f.id);
    if (ids.length === 0) return;
    const typed = window.prompt(
      `完全に削除すると元に戻せません（回答も消えます）。\n選択した ${ids.length} 件を削除するには「削除」と入力してください。`,
      '',
    );
    if (typed !== '削除') return;
    setBulkResult(null);
    summarize(await removeMany(ids), '完全に削除しました');
    await mutate();
    setSelected(new Set());
  };

  const openWizard = (next: 'application' | 'navigation') => {
    setWizardKind(next);
    setWizardOpen(true);
  };

  useEffect(() => {
    if (searchParams.get('tab') !== 'new' && searchParams.get('intent') !== 'guide') return;
    setWizardKind(
      searchParams.get('kind') === 'navigation' || searchParams.get('intent') === 'guide'
        ? 'navigation'
        : 'application',
    );
    setWizardOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete('tab');
    next.delete('intent');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const onExportForm = async (id: string) => {
    setImportMsg(null);
    setExportingId(id);
    try {
      await downloadFormPortable(id);
    } catch {
      setImportMsg('書き出しに失敗しました。');
    } finally {
      setExportingId(null);
    }
  };

  const onDuplicateForm = async (id: string) => {
    setImportMsg(null);
    setDuplicatingId(id);
    try {
      const created = await duplicateForm(id);
      if (created) {
        await mutate();
        setImportMsg(`「${created.title}」を複製しました（未公開）。`);
      }
    } finally {
      setDuplicatingId(null);
    }
  };

  const onImportFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setImportMsg(null);
    try {
      const bundle = await readExportBundleFile(file);
      if (bundle.kind !== 'form') {
        setImportMsg('これは手続きの書き出しファイルです。手続き一覧の「読み込み」からお試しください。');
        return;
      }
      const created = await importForm(bundle);
      if (created) {
        await mutate();
        setImportMsg(`「${created.title}」を取り込みました（作成完了・未公開）。`);
      }
    } catch (err) {
      setImportMsg(err instanceof Error ? err.message : '取り込みに失敗しました。');
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={PATCHFORM_LABEL} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={PATCHFORM_EXAPP_ID}
          fallbackTitle={PATCHFORM_LABEL}
          fallbackDescription='記入してもらう用紙と、申請者の状況を聞く入口を作ります。'
          hideHowTo
        >
          <PatchformSubnav current='forms' />
        </ManagedAppHeader>

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              {PATCHFORM_LABEL}は現在有効化されていません
            </p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error || 'コンテナを profiles: ["patchform"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile patchform up -d{'\n'}
              # または .env に COMPOSE_PROFILES=patchform
            </pre>
          </div>
        )}

        {!unavailable && (
          <>
            <PatchformPaneTabs
              label='フォームの一覧'
              current={kind === 'navigation' ? 'nav-list' : 'app-list'}
              tabs={[
                {
                  id: 'app-list',
                  label: `申請フォーム一覧（${appActiveCount}）`,
                  to: '/patchform',
                  icon: PiListBold,
                },
                {
                  id: 'nav-list',
                  label: `ナビゲーションフォーム一覧（${navActiveCount}）`,
                  to: '/patchform?kind=navigation',
                  icon: PiListBold,
                },
              ]}
            />
            <section className='flex flex-col gap-3'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <h2 className='text-std-18B-160'>
                  {asGuide ? 'ナビゲーションフォーム一覧' : '申請フォーム一覧'}
                </h2>
                <div className='flex flex-wrap items-center gap-2'>
                  <input
                    ref={importInputRef}
                    type='file'
                    accept='application/json,.json'
                    className='hidden'
                    onChange={onImportFile}
                  />
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    aria-disabled={submitting}
                    onClick={() => importInputRef.current?.click()}
                  >
                    読み込み
                  </Button>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='sm'
                    onClick={() => openWizard(kind)}
                  >
                    {asGuide ? '新しいナビゲーションフォームを作る' : '新しい申請フォームを作る'}
                  </Button>
                </div>
              </div>
              {importMsg ? (
                <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
                  {importMsg}
                </p>
              ) : null}
              <fieldset className='m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0' aria-label='状態で絞り込み'>
                {(
                  [
                    { id: '', label: `すべて（${activeCount}）` },
                    { id: 'editing', label: '作成中' },
                    { id: 'ready', label: '作成完了' },
                    { id: 'trash', label: `ゴミ箱（${trashCount}）` },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id || 'all'}
                    type='button'
                    onClick={() => selectFilter(t.id)}
                    className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                      statusFilter === t.id
                        ? 'border-blue-900 bg-blue-50 text-blue-900'
                        : t.id === 'trash'
                          ? 'border-solid-gray-420 text-solid-gray-600'
                          : 'border-solid-gray-420 text-solid-gray-700'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </fieldset>
              {!trashView && knownTags.length > 0 ? (
                <fieldset className='m-0 flex min-w-0 flex-wrap items-center gap-2 border-0 p-0' aria-label='タグで絞り込み'>
                  <button
                    type='button'
                    onClick={() => setTagFilter('')}
                    className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                      tagFilter === ''
                        ? 'border-blue-900 bg-blue-50 text-blue-900'
                        : 'border-solid-gray-420 text-solid-gray-700'
                    }`}
                  >
                    すべてのタグ
                  </button>
                  {knownTags.map((tag) => (
                    <button
                      key={tag}
                      type='button'
                      onClick={() => setTagFilter(tag)}
                      className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                        tagFilter === tag
                          ? 'border-blue-900 bg-blue-50 text-blue-900'
                          : 'border-solid-gray-420 text-solid-gray-700'
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                  <button
                    type='button'
                    onClick={() => setTagManagerOpen((v) => !v)}
                    className='ml-1 rounded-4 border border-dashed border-solid-gray-420 px-3 py-1 text-dns-16N-130 text-solid-gray-700 hover:bg-solid-gray-50'
                    aria-expanded={tagManagerOpen}
                  >
                    {tagManagerOpen ? 'タグ管理を閉じる' : 'タグを管理'}
                  </button>
                </fieldset>
              ) : null}

              {!trashView && tagManagerOpen ? (
                <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                  <h3 className='text-std-16B-150'>タグの管理</h3>
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    タグは各フォームに付いたラベルの集まりです（マスタはありません）。改名・削除は編集権限のある全フォーム（ゴミ箱内も含む）へまとめて反映されます。あるタグが付いたフォームが0件になると、そのタグは自動的に消えます。
                  </p>
                  {tagActionError && (
                    <p className='mt-2 text-dns-14N-130 text-error-1' role='alert'>
                      {tagActionError}
                    </p>
                  )}
                  {tagUsage.length === 0 ? (
                    <p className='mt-3 text-dns-14N-130 text-solid-gray-600'>
                      管理できるタグはありません。
                    </p>
                  ) : (
                    <ul className='mt-3 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                      {tagUsage.map((t) => (
                        <li
                          key={t.tag}
                          className='flex flex-wrap items-center justify-between gap-2 py-2'
                        >
                          <span className='text-std-16N-170'>
                            {t.tag}
                            <span className='ml-2 text-dns-14N-130 text-solid-gray-500'>
                              {t.count} 件
                            </span>
                          </span>
                          <span className='flex gap-1'>
                            <button
                              type='button'
                              className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                              aria-disabled={tagBusy}
                              onClick={() => void onRenameTag(t.tag)}
                            >
                              改名
                            </button>
                            <button
                              type='button'
                              className='rounded-4 border border-error-1 bg-red-50 px-2 py-1 text-dns-14N-130 text-error-1'
                              aria-disabled={tagBusy}
                              onClick={() => void onDeleteTag(t.tag, t.count)}
                            >
                              削除
                            </button>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
              {isLoading ? (
                <p className='text-solid-gray-600'>読み込み中...</p>
              ) : loadError ? (
                <p className='text-error-1' role='alert'>
                  {loadError}
                </p>
              ) : visibleForms.length === 0 ? (
                <div className='text-solid-gray-600'>
                  {trashView
                    ? 'ゴミ箱は空です。'
                    : kindForms.length === 0
                      ? asGuide
                        ? 'まだナビゲーションフォームがありません。'
                        : 'まだ申請フォームがありません。'
                      : 'この条件のフォームはありません。'}
                  {!trashView && kindForms.length === 0 ? (
                    <span className='mt-3 block'>
                      <Button type='button' variant='solid-fill' size='sm' onClick={() => openWizard(kind)}>
                        {asGuide ? '新しいナビゲーションフォームを作る' : '新しい申請フォームを作る'}
                      </Button>
                    </span>
                  ) : null}
                </div>
              ) : (
                <>
                  {selectableVisible.length > 0 ? (
                    <div className='flex flex-wrap items-center gap-3 rounded-4 border border-solid-gray-300 bg-solid-gray-50 px-3 py-2'>
                      <label className='flex items-center gap-2 text-dns-16N-130 text-solid-gray-700'>
                        <input
                          type='checkbox'
                          className='size-5'
                          checked={allSelected}
                          ref={(el) => {
                            if (el) el.indeterminate = selectedCount > 0 && !allSelected;
                          }}
                          onChange={toggleAll}
                        />
                        すべて選択
                      </label>
                      <span className='text-dns-14N-130 text-solid-gray-600'>
                        {selectedCount > 0 ? `${selectedCount} 件を選択中` : '選択して一括処理できます'}
                      </span>
                      {trashView ? (
                        <div className='flex flex-wrap items-center gap-2'>
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            aria-disabled={submitting || selectedCount === 0}
                            onClick={() => void onRestore()}
                          >
                            {submitting ? '処理中...' : `復元する${selectedCount > 0 ? `（${selectedCount}）` : ''}`}
                          </Button>
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            className='border-error-1 text-error-1'
                            aria-disabled={submitting || selectedCount === 0}
                            onClick={() => void onPurge()}
                          >
                            {submitting ? '処理中...' : '完全に削除'}
                          </Button>
                        </div>
                      ) : (
                        <>
                        <div className='flex flex-wrap items-center gap-2'>
                          <select
                            className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-16N-130'
                            value={bulkAction}
                            onChange={(e) => chooseBulkAction(e.target.value)}
                            aria-label='一括処理を選ぶ'
                          >
                            <option value=''>一括処理を選ぶ…</option>
                            <option value='ready'>作成完了にする</option>
                            <option value='editing'>作成に戻す</option>
                            <option value='tag_add'>タグを付ける</option>
                            <option value='tag_remove'>タグを外す</option>
                            <option value='archive'>ゴミ箱へ移す</option>
                          </select>
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            aria-disabled={
                              submitting ||
                              selectedCount === 0 ||
                              !bulkAction ||
                              ((bulkAction === 'tag_add' || bulkAction === 'tag_remove') &&
                                tagTargets.length === 0 &&
                                !(bulkAction === 'tag_add' && tagDraft.trim()))
                            }
                            onClick={() => void runBulk()}
                          >
                            {submitting ? '処理中...' : '実行'}
                          </Button>
                        </div>
                        {bulkAction === 'tag_add' ? (
                          <div className='flex w-full flex-col gap-2'>
                            {tagTargets.length > 0 ? (
                              <ul className='flex flex-wrap gap-2'>
                                {tagTargets.map((tag) => (
                                  <li key={tag}>
                                    <button
                                      type='button'
                                      className='rounded-4 border border-solid-gray-420 bg-white px-2 py-1 text-dns-14N-130 text-solid-gray-800'
                                      onClick={() => toggleTagTarget(tag)}
                                      aria-label={`${tag}を候補から外す`}
                                    >
                                      {tag} ×
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            ) : null}
                            <div className='flex flex-wrap items-center gap-2'>
                              <input
                                className='w-full max-w-64 rounded-4 border border-solid-gray-420 px-3 py-1.5 text-std-16N-170'
                                value={tagDraft}
                                onChange={(e) => setTagDraft(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ',') {
                                    e.preventDefault();
                                    addTagTarget(tagDraft);
                                  }
                                }}
                                placeholder='付けるタグを入力（Enterで追加）'
                              />
                              <button
                                type='button'
                                className='rounded-4 border border-solid-gray-420 px-3 py-1.5 text-dns-16N-130 text-solid-gray-800'
                                disabled={!tagDraft.trim()}
                                onClick={() => addTagTarget(tagDraft)}
                              >
                                追加
                              </button>
                            </div>
                            {knownTags.filter((t) => !tagTargets.includes(t)).length > 0 ? (
                              <div className='flex flex-wrap gap-2'>
                                {knownTags
                                  .filter((t) => !tagTargets.includes(t))
                                  .slice(0, 12)
                                  .map((tag) => (
                                    <button
                                      key={tag}
                                      type='button'
                                      className='rounded-4 border border-dashed border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                                      onClick={() => addTagTarget(tag)}
                                    >
                                      {tag}
                                    </button>
                                  ))}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {bulkAction === 'tag_remove' ? (
                          <div className='flex w-full flex-col gap-2'>
                            {selectedTags.length === 0 ? (
                              <p className='text-dns-14N-130 text-solid-gray-600'>
                                選択したフォームに付いているタグはありません。
                              </p>
                            ) : (
                              <div className='flex flex-wrap gap-2'>
                                {selectedTags.map((tag) => (
                                  <button
                                    key={tag}
                                    type='button'
                                    className={`rounded-4 border px-2 py-1 text-dns-14N-130 ${
                                      tagTargets.includes(tag)
                                        ? 'border-blue-900 bg-blue-50 text-blue-900'
                                        : 'border-solid-gray-420 text-solid-gray-700'
                                    }`}
                                    onClick={() => toggleTagTarget(tag)}
                                  >
                                    {tag}
                                    {tagTargets.includes(tag) ? ' ✓' : ''}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : null}
                        </>
                      )}
                    </div>
                  ) : null}
                  {trashView ? (
                    <p className='text-dns-14N-130 text-solid-gray-600'>
                      削除は「ゴミ箱へ移す」で退避してから、ここで完全に削除します。完全削除は元に戻せません。
                    </p>
                  ) : null}
                  {bulkResult ? (
                    <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
                      {bulkResult}
                    </p>
                  ) : null}
                  <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                    {visibleForms.map((f) => (
                      <li key={f.id} className='flex items-start gap-3 py-3'>
                        {f.can_edit ? (
                          <input
                            type='checkbox'
                            className='mt-0.5 size-5 flex-none'
                            checked={selected.has(f.id)}
                            onChange={() => toggleOne(f.id)}
                            aria-label={`「${f.title}」を選択`}
                          />
                        ) : (
                          <span className='mt-0.5 size-5 flex-none' aria-hidden='true' />
                        )}
                        <div className='min-w-0 flex-1'>
                          {trashView ? (
                            <span className='text-std-16B-150 text-solid-gray-800'>{f.title}</span>
                          ) : (
                            <Link
                              to={`/patchform/${f.id}`}
                              className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                            >
                              {f.title}
                            </Link>
                          )}
                          <FormTagList tags={f.tags} />
                          <p className='text-dns-14N-130 text-solid-gray-600'>
                            {trashView ? 'ゴミ箱' : workLabel(f.locked, f.work_status)}
                            {f.has_opening ? ' / 受付中' : ''}
                            {(f.reception_count ?? 0) > 0 ? ` / 窓口 ${f.reception_count} 回` : ''}
                            {f.role === 'editor'
                              ? ' / 編集者'
                              : f.role === 'viewer'
                                ? ' / 閲覧者'
                                : f.role === 'respondent'
                                  ? ' / 回答'
                                  : ''}
                            {' / '}
                            {new Date(f.updated_at).toLocaleString('ja-JP')}
                          </p>
                        </div>
                        {f.can_edit ? (
                          <div className='mt-0.5 flex flex-none gap-2'>
                            <button
                              type='button'
                              className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700 hover:bg-solid-gray-50'
                              aria-disabled={duplicatingId === f.id}
                              onClick={() => void onDuplicateForm(f.id)}
                            >
                              {duplicatingId === f.id ? '複製中...' : '複製'}
                            </button>
                            <button
                              type='button'
                              className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700 hover:bg-solid-gray-50'
                              aria-disabled={exportingId === f.id}
                              onClick={() => void onExportForm(f.id)}
                            >
                              {exportingId === f.id ? '書き出し中...' : '書き出し'}
                            </button>
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
            <FormCreateWizard
              open={wizardOpen}
              kind={wizardKind}
              onClose={() => setWizardOpen(false)}
              onCreated={(created) => {
                setWizardOpen(false);
                void mutate();
                navigate(
                  wizardKind === 'navigation'
                    ? `/patchform/${created.id}/edit?intent=guide`
                    : `/patchform/${created.id}/edit`,
                );
              }}
            />
          </>
        )}
      </div>
    </LayoutBody>
  );
};
