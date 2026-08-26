import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { PiBookOpenBold, PiListBold, PiNotePencilBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { FormTagList, FormTagsField } from './FormTagsField';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformPaneTabs } from './PatchformPaneTabs';
import { PatchformSubnav } from './PatchformSubnav';
import {
  usePatchformActions,
  usePatchformAssist,
  usePatchformConfig,
  usePatchformList,
} from './usePatchform';

const workLabel = (locked?: boolean, workStatus?: string | null) =>
  locked || workStatus === 'ready' ? '作成完了' : '作成中';

/**
 * フォーム専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["patchform"] 未起動時は有効化手順を案内する。
 */
export const PatchformPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fromGuideLink = searchParams.get('intent') === 'guide';
  const pane = searchParams.get('tab') === 'new' || fromGuideLink ? 'new' : 'list';
  const { config, isLoading: configLoading, unavailable } = usePatchformConfig();
  const { forms, isLoading, loadError, mutate } = usePatchformList();
  const {
    create,
    setStatusMany,
    applyTagsMany,
    removeMany,
    submitting,
    error,
    setError,
  } = usePatchformActions();
  const {
    generate,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const [formKind, setFormKind] = useState<'application' | 'navigation'>(
    fromGuideLink ? 'navigation' : 'application',
  );
  const asGuide = formKind === 'navigation';
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [aiText, setAiText] = useState('');
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [tags, setTags] = useState<string[]>(fromGuideLink ? [NAVIGATION_TAG] : []);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  const [bulkAction, setBulkAction] = useState('');
  const [tagTargets, setTagTargets] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState('');
  const knownTags = [...new Set(forms.flatMap((f) => f.tags || []))].sort();
  const activeCount = forms.filter((f) => f.status !== 'archived').length;
  const trashCount = forms.filter((f) => f.status === 'archived').length;
  const trashView = statusFilter === 'trash';

  const visibleForms = forms.filter((f) => {
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

  const chooseKind = (kind: 'application' | 'navigation') => {
    setFormKind(kind);
    setTags((prev) => {
      const without = prev.filter((t) => t !== NAVIGATION_TAG);
      return kind === 'navigation' ? [NAVIGATION_TAG, ...without] : without;
    });
  };

  useEffect(() => {
    if (pane !== 'new') return;
    document.getElementById('pf-title')?.focus();
  }, [pane]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError('タイトルを入力してください。');
      return;
    }
    const detail = await create({
      title: title.trim(),
      description: description.trim() || undefined,
      visibility: 'internal',
      tags,
    });
    if (detail) {
      await mutate();
      navigate(asGuide ? `/patchform/${detail.id}/edit?intent=guide` : `/patchform/${detail.id}/edit`);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={PATCHFORM_LABEL} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <div className='flex flex-col gap-4'>
          <BreadcrumbsNav
            items={[
              { label: 'ホーム', to: '/' },
              { label: 'AIアプリ', to: '/apps' },
              { label: PATCHFORM_LABEL },
            ]}
          />
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>{PATCHFORM_LABEL}</h1>
          <PatchformSubnav current='forms' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            フォームを作成することができます。「一覧」で作成したフォームを見ることができます。「作成」で申請フォームやナビゲーションフォームの作成ができます。
          </p>
          <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
            <DisclosureSummary>
              <span className='flex items-center text-std-16B-150'>
                <PiBookOpenBold className='mr-2 size-5 flex-none' />
                使い方（クリックで開閉）
              </span>
            </DisclosureSummary>
            <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
              <p>・タイトルを付けて作成し、編集画面で部品を並べます。1枚だけの手続きではタグは不要です。答えで用紙を足すナビゲーションフォームには、ラジオやプルダウンを入れ、「ナビゲーション」タグを付けてください。</p>
              <p>・受付は「手続き」を公開すると始まります。届いた件は「申請受付」にあります。</p>
              <p>・外部 URL は「手続きを公開」にあります。LGWAN から届かない場合は、そこのリンクファイルを持ち出して別端末で開いてください。</p>
              <p>
                ・有効化: <code>docker compose --profile patchform up -d</code> または{' '}
                <code>COMPOSE_PROFILES=patchform</code>
              </p>
              {config?.retention_days != null && (
                <p>・既定の保持期間は {config.retention_days} 日です（フォームごとに変更できます）。</p>
              )}
            </div>
          </Disclosure>
        </div>

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
              label='フォームの作成と一覧'
              current={pane}
              tabs={[
                { id: 'list', label: `一覧（${activeCount}）`, to: '/patchform', icon: PiListBold },
                {
                  id: 'new',
                  label: '作成',
                  to: fromGuideLink ? '/patchform?tab=new&intent=guide' : '/patchform?tab=new',
                  icon: PiNotePencilBold,
                },
              ]}
            />
            {pane === 'new' ? (
            <section id='pf-new-form' className='flex flex-col gap-4'>
              <h2 className='flex items-center gap-2 text-std-18B-160'>
                <PiNotePencilBold className='size-5' />
                新しいフォーム
              </h2>
              <form onSubmit={onSubmit} className='flex flex-col gap-4'>
                <fieldset>
                  <legend className='text-std-16B-150'>種類</legend>
                  <div className='mt-2 flex flex-col gap-2'>
                    <label className='flex items-start gap-2 text-std-16N-170'>
                      <input
                        type='radio'
                        name='pf-form-kind'
                        className='mt-1'
                        checked={!asGuide}
                        onChange={() => chooseKind('application')}
                      />
                      <span>
                        申請フォームを作る
                        <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                          1枚の申請やお問い合わせなど、記入してもらう用紙です。
                        </span>
                      </span>
                    </label>
                    <label className='flex items-start gap-2 text-std-16N-170'>
                      <input
                        type='radio'
                        name='pf-form-kind'
                        className='mt-1'
                        checked={asGuide}
                        onChange={() => chooseKind('navigation')}
                      />
                      <span>
                        ナビゲーションフォームを作る
                        <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                          申請者の状況を聞き、必要な申請フォームの組み合わせを決めます。ラジオやプルダウンを入れてください。
                        </span>
                      </span>
                    </label>
                  </div>
                </fieldset>
                <div>
                  <Label htmlFor='pf-title' size='sm'>
                    タイトル
                  </Label>
                  <input
                    id='pf-title'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={asGuide ? '例: 転入・転居の確認' : '例: 転入届'}
                    required
                  />
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    一覧と入力画面の見出しに出ます。
                  </p>
                </div>
                <div>
                  <Label htmlFor='pf-desc' size='sm'>
                    説明（任意）
                  </Label>
                  <textarea
                    id='pf-desc'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder='例: 転入か転居かを確認します'
                  />
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                    入力画面の案内文です。空欄でも構いません。
                  </p>
                </div>
                <FormTagsField
                  id='pf-tags'
                  value={tags}
                  onChange={setTags}
                  suggestions={knownTags}
                />
                <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                  <Label htmlFor='pf-ai' size='sm'>
                    AIで下書きを作る
                  </Label>
                  <textarea
                    id='pf-ai'
                    className='w-full rounded-4 border border-solid-gray-420 bg-white px-3 py-2 text-std-16N-170'
                    rows={2}
                    value={aiText}
                    onChange={(e) => setAiText(e.target.value)}
                    placeholder='例: 子ども医療費助成の申請。申請者・住所・振込先が必要'
                  />
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    モデル: {config?.llm?.model || '（未設定）'}。失敗時はテンプレートにフォールバックします。
                  </p>
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
                      aria-disabled={assistBusy || submitting || !aiText.trim()}
                      onClick={async () => {
                        setAssistError(null);
                        setAiNotes(null);
                        const res = await generate({ text: aiText.trim() });
                        if (!res) return;
                        const created = await create({
                          title: res.definition.metadata.title || title.trim() || 'AI下書き',
                          description: res.definition.metadata.description || description.trim() || undefined,
                          definition: res.definition,
                          visibility: 'internal',
                          tags,
                        });
                        if (created) {
                          await mutate();
                          navigate(
                            asGuide
                              ? `/patchform/${created.id}/edit?intent=guide`
                              : `/patchform/${created.id}/edit`,
                          );
                        } else {
                          setAiNotes(res.notes || '下書きを生成しましたが、作成に失敗しました。');
                        }
                      }}
                    >
                      {assistBusy || submitting ? '生成中...' : '生成して編集する'}
                    </Button>
                  </div>
                </div>
                {error && (
                  <p className='text-dns-16N-130 text-error-1' role='alert'>
                    {error}
                  </p>
                )}
                <div>
                  <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
                    {submitting ? '作成中...' : '作成して編集する'}
                  </Button>
                </div>
              </form>
            </section>
            ) : (
            <section className='flex flex-col gap-3'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <h2 className='text-std-18B-160'>フォーム一覧</h2>
                <Link to='/patchform?tab=new' className='inline-flex'>
                  <Button type='button' variant='solid-fill' size='sm'>
                    新しいフォームを作る
                  </Button>
                </Link>
              </div>
              <div className='flex flex-wrap gap-2' role='group' aria-label='状態で絞り込み'>
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
              </div>
              {!trashView && knownTags.length > 0 ? (
                <div className='flex flex-wrap gap-2' role='group' aria-label='タグで絞り込み'>
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
                </div>
              ) : null}
              {isLoading ? (
                <p className='text-solid-gray-600'>読み込み中...</p>
              ) : loadError ? (
                <p className='text-error-1' role='alert'>
                  {loadError}
                </p>
              ) : visibleForms.length === 0 ? (
                <p className='text-solid-gray-600'>
                  {trashView ? (
                    'ゴミ箱は空です。'
                  ) : forms.length === 0 ? (
                    <>
                      まだフォームがありません。
                      <Link
                        to='/patchform?tab=new'
                        className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                      >
                        作成タブから作る
                      </Link>
                    </>
                  ) : (
                    'この条件のフォームはありません。'
                  )}
                </p>
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
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};
