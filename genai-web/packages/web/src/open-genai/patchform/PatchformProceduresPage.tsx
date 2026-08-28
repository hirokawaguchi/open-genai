import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { PiListBold, PiNotePencilBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { PatchformGuideAssist } from './PatchformGuideAssist';
import { PatchformPaneTabs } from './PatchformPaneTabs';
import { PatchformSubnav } from './PatchformSubnav';
import { ProcedureReceptionActions } from './ProcedureReceptionActions';
import { omitsNavigation } from './types';
import {
  extractPatchformFile,
  usePatchformAssist,
  usePatchformConfig,
  usePatchformList,
  usePatchformProcedureActions,
  usePatchformProcedures,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
  archived: 'ゴミ箱',
};

export const PatchformProceduresPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const pane = searchParams.get('tab') === 'new' ? 'new' : 'list';
  const { config } = usePatchformConfig();
  const { forms, mutate: mutateForms } = usePatchformList();
  const { procedures, isLoading, loadError, mutate } = usePatchformProcedures();
  const { create, setStatus, setStatusMany, removeMany, submitting, error, setError } =
    usePatchformProcedureActions();
  const {
    previewProcedure,
    applyProcedureDraft,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [guideFormId, setGuideFormId] = useState('');
  const [startMode, setStartMode] = useState<'omit' | 'navigate'>('omit');
  const [guideText, setGuideText] = useState('');
  const [readingFile, setReadingFile] = useState(false);
  const [guideFileName, setGuideFileName] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  const [bulkAction, setBulkAction] = useState('');
  const [trashView, setTrashView] = useState(false);

  const activeCount = procedures.filter((p) => p.status !== 'archived').length;
  const trashCount = procedures.filter((p) => p.status === 'archived').length;
  const visibleProcs = procedures.filter((p) =>
    trashView ? p.status === 'archived' : p.status !== 'archived',
  );
  const selectableVisible = visibleProcs.filter((p) => p.can_edit);
  const selectedCount = selectableVisible.filter((p) => selected.has(p.id)).length;
  const allSelected = selectableVisible.length > 0 && selectedCount === selectableVisible.length;
  const selectedProcs = selectableVisible.filter((p) => selected.has(p.id));
  const nameOf = (id: string) => procedures.find((p) => p.id === id)?.name || id;

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
        for (const p of selectableVisible) next.delete(p.id);
      } else {
        for (const p of selectableVisible) next.add(p.id);
      }
      return next;
    });

  const switchView = (trash: boolean) => {
    setTrashView(trash);
    setSelected(new Set());
    setBulkResult(null);
    setBulkAction('');
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
          ng.map((r) => `「${nameOf(r.id)}」: ${r.error}`).join(' / ') +
          '）。',
      );
    }
    setBulkResult(parts.join(''));
  };

  const runBulk = async () => {
    const ids = selectedProcs.map((p) => p.id);
    if (ids.length === 0 || !bulkAction) return;
    setBulkResult(null);
    if (bulkAction === 'close') {
      if (
        !window.confirm(
          `選択した ${ids.length} 件の受付を終了します。新しい申請は止まりますが、届いている申請は残ります。`,
        )
      )
        return;
      summarize(await setStatusMany(ids, 'draft'), '受付を終了しました');
    } else if (bulkAction === 'archive') {
      if (
        !window.confirm(
          `選択した ${ids.length} 件をゴミ箱へ移します。公開中のものは先に受付終了が必要です。あとで復元できます。`,
        )
      )
        return;
      summarize(await setStatusMany(ids, 'archived'), 'ゴミ箱へ移しました');
    }
    await mutate();
    setSelected(new Set());
    setBulkAction('');
  };

  const onRestore = async () => {
    const ids = selectedProcs.map((p) => p.id);
    if (ids.length === 0) return;
    setBulkResult(null);
    summarize(await setStatusMany(ids, 'draft'), '復元しました');
    await mutate();
    setSelected(new Set());
  };

  const onPurge = async () => {
    const ids = selectedProcs.map((p) => p.id);
    if (ids.length === 0) return;
    const typed = window.prompt(
      `完全に削除すると元に戻せません。\n選択した ${ids.length} 件を削除するには「削除」と入力してください。`,
      '',
    );
    if (typed !== '削除') return;
    setBulkResult(null);
    summarize(await removeMany(ids), '完全に削除しました');
    await mutate();
    setSelected(new Set());
  };

  const draftProc = procedures.find((p) => p.status === 'draft');
  const publishedProc = procedures.find((p) => p.status === 'published');
  const omitNav = startMode === 'omit';
  const isNavForm = (f: (typeof forms)[number]) => (f.tags || []).includes(NAVIGATION_TAG);
  const selectableForms = forms.filter(
    (f) => f.status !== 'archived' && (omitNav ? !isNavForm(f) : isNavForm(f)),
  );

  const chooseStartMode = (mode: 'omit' | 'navigate') => {
    setStartMode(mode);
    const keep = forms.find((f) => f.id === guideFormId);
    const ok = keep && (mode === 'omit' ? !isNavForm(keep) : isNavForm(keep));
    if (!ok) setGuideFormId('');
  };

  const goCreate = () => {
    if (pane === 'new') {
      document.getElementById('pf-proc-name')?.focus();
      document.getElementById('pf-proc-create')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    navigate('/patchform/procedures?tab=new');
  };

  const onPickGuide = async (file: File | null) => {
    if (!file) return;
    setAssistError(null);
    setReadingFile(true);
    try {
      const res = await extractPatchformFile('document', file);
      const extracted = (res.extracted || '').trim();
      if (!extracted) {
        setAssistError(
          res.notes
          || 'このファイルから本文を取れませんでした。txt / md / pdf / docx / xlsx を選んでください。',
        );
        return;
      }
      setGuideText(extracted);
    } catch {
      setAssistError('ファイルの読み取りに失敗しました。txt / md / pdf / docx / xlsx を選んでください。');
    } finally {
      setReadingFile(false);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !guideFormId) {
      setError(omitNav ? '名前と申請フォームを選んでください。' : '名前とナビゲーションフォームを選んでください。');
      return;
    }
    const created = await create({
      name: name.trim(),
      description: description.trim() || undefined,
      guide_form_id: guideFormId,
    });
    if (created) {
      await mutate();
      navigate(`/patchform/procedures/${created.id}`);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={`手続き · ${PATCHFORM_LABEL}`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '手続き' },
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>手続き</h1>
          <PatchformSubnav current='procedures' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            手続きを公開して、受付可能な状態にします。「一覧」で公開中の手続きを見ることができます。「作成」で新たに手続きを作成します。
          </p>
        </div>

        <PatchformPaneTabs
          label='手続きの作成と一覧'
          current={pane}
          tabs={[
            { id: 'list', label: `一覧（${activeCount}）`, to: '/patchform/procedures', icon: PiListBold },
            { id: 'new', label: '作成', to: '/patchform/procedures?tab=new', icon: PiNotePencilBold },
          ]}
        />

        {pane === 'new' ? (
        <>
        <PatchformProcedureCoach
          title='操作の流れ'
          lead='今の段階が枠で示されます。ボタンを押すと次の画面へ進みます。'
          steps={[
            {
              id: 'guide',
              label: 'フォームを作成する',
              done: forms.length > 0 || procedures.length > 0,
              hint: '申請フォームかナビゲーションフォームを、「フォーム作成」で作ります。',
              action: { label: 'フォーム作成へ', to: '/patchform?tab=new' },
            },
            {
              id: 'map',
              label: '手続きを作る',
              done: procedures.length > 0,
              hint: '下の作成欄から始めます。1枚だけなら「ナビゲーションフォームは使わない」を選びます。',
              action: { label: '下の作成欄へ', onClick: goCreate },
            },
            {
              id: 'publish',
              label: '手続きを公開する',
              done: Boolean(publishedProc),
              hint: '公開すると、申請者や回答者が使える受付が始まります。',
              action: draftProc
                ? { label: `「${draftProc.name}」を開く`, to: `/patchform/procedures/${draftProc.id}` }
                : { label: '作成タブへ', onClick: goCreate },
            },
            {
              id: 'try',
              label: '届いた申請は申請受付で見る',
              done: false,
              hint: '申請者や回答者が質問に答えると、必要な申請の一覧ができます。進捗は申請受付で見ます。',
              action: { label: '申請受付を開く', to: '/patchform/inbox' },
            },
          ]}
        />

        <section id='pf-proc-create' className='flex flex-col gap-4'>
          <h2 className='text-std-18B-160'>新しい手続き</h2>
          <p className='text-std-16N-170 text-solid-gray-700'>
            手続きを作成して公開します。手順に沿って作業してください。
          </p>
          <div className='rounded-8 border border-solid-gray-420 bg-white px-4 py-4'>
            {forms.length === 0 ? (
              <div className='mt-4 flex flex-col gap-3'>
                <p className='text-dns-16N-130 text-solid-gray-700'>
                  まだ選べるフォームがありません。先にフォームを作成してください。
                </p>
                <div>
                  <Link to='/patchform?tab=new' className='inline-flex'>
                    <Button type='button' variant='solid-fill' size='md'>
                      フォームを作成する
                    </Button>
                  </Link>
                </div>
              </div>
            ) : (
            <form onSubmit={(e) => void onSubmit(e)} className='mt-6 flex flex-col gap-4'>
              <div>
                <Label htmlFor='pf-proc-name' size='sm'>
                  名前
                </Label>
                <input
                  id='pf-proc-name'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder='例: 転入の手続き'
                  required
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  庁内の一覧で使う名前です。
                </p>
              </div>
              <div>
                <Label htmlFor='pf-proc-desc' size='sm'>
                  説明（任意）
                </Label>
                <textarea
                  id='pf-proc-desc'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder='例: 転入・転居のときに出す書類を振り分けます'
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  職員向けのメモです。空欄でも構いません。
                </p>
              </div>
              <fieldset>
                <legend className='text-std-16B-150'>始め方</legend>
                <div className='mt-2 flex flex-col gap-2'>
                  <label className='flex items-start gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-proc-start'
                      className='mt-1'
                      checked={omitNav}
                      onChange={() => chooseStartMode('omit')}
                    />
                    <span>
                      ナビゲーションフォームは使わない
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                        申請フォーム１枚だけの手続きの場合は、ナビゲーションフォームは不要です。
                      </span>
                    </span>
                  </label>
                  <label className='flex items-start gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-proc-start'
                      className='mt-1'
                      checked={!omitNav}
                      onChange={() => chooseStartMode('navigate')}
                    />
                    <span>
                      ナビゲーションフォームを使う
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                        申請者の状況に応じて複数の申請フォームの組み合わせを変える場合に使います。
                      </span>
                    </span>
                  </label>
                </div>
              </fieldset>
              <div>
                <Label htmlFor='pf-proc-guide' size='sm'>
                  {omitNav ? '申請フォーム' : 'ナビゲーションフォーム'}
                </Label>
                <select
                  id='pf-proc-guide'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  value={guideFormId}
                  onChange={(e) => setGuideFormId(e.target.value)}
                  required
                >
                  <option value=''>{omitNav ? '申請フォームを選ぶ' : 'ナビゲーションフォームを選ぶ'}</option>
                  {selectableForms.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.title}（{f.locked || f.work_status === 'ready' ? '作成完了' : '作成中'}
                      {f.has_opening ? ' · 受付中' : ''}
                      {(f.tags || []).length ? ` · ${(f.tags || []).join('、')}` : ''}）
                    </option>
                  ))}
                </select>
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  表示させるフォームを選んでください。
                </p>
                {selectableForms.length === 0 ? (
                  <div className='mt-2 flex flex-col items-start gap-2'>
                    <p className='text-dns-16N-130 text-solid-gray-700'>
                      {omitNav
                        ? '選べる申請フォームがありません。'
                        : '選べるナビゲーションフォームがありません。'}
                    </p>
                    <Button asChild variant='outline' size='sm' className='inline-flex items-center justify-center'>
                      <Link to='/patchform?tab=new'>フォームを作成する</Link>
                    </Button>
                  </div>
                ) : null}
              </div>
              {error && (
                <p className='text-error-1' role='alert'>
                  {error}
                </p>
              )}
              <div>
                <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
                  {submitting ? '作成中...' : '作成して編集する'}
                </Button>
              </div>
            </form>
            )}
          </div>

          <p className='text-center text-std-16B-150 text-solid-gray-700'>または</p>

          <PatchformGuideAssist
            model={config?.llm?.model}
            readingFile={readingFile}
            guideFileName={guideFileName}
            guideText={guideText}
            busy={assistBusy}
            error={assistError}
            setError={setAssistError}
            onPickFile={(file) => {
              setGuideFileName(file?.name || '');
              void onPickGuide(file);
            }}
            previewProcedure={previewProcedure}
            applyProcedureDraft={applyProcedureDraft}
            onApplied={async (res) => {
              await Promise.all([mutate(), mutateForms()]);
              if (res.procedure?.id) {
                navigate(`/patchform/procedures/${res.procedure.id}`);
                return;
              }
              const nav = res.created_forms.find((f) => f.role === 'guide');
              const first = res.created_forms[0];
              if (nav) navigate(`/patchform/${nav.id}`);
              else if (first) navigate(`/patchform/${first.id}`);
              else navigate('/patchform');
            }}
          />
        </section>
        </>
        ) : (
        <section className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h2 className='text-std-18B-160'>手続き一覧</h2>
            <Link to='/patchform/procedures?tab=new' className='inline-flex'>
              <Button type='button' variant='solid-fill' size='sm'>
                新しい手続きを作る
              </Button>
            </Link>
          </div>
          <fieldset className='m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0' aria-label='表示の切り替え'>
            <button
              type='button'
              onClick={() => switchView(false)}
              className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                !trashView
                  ? 'border-blue-900 bg-blue-50 text-blue-900'
                  : 'border-solid-gray-420 text-solid-gray-700'
              }`}
            >
              一覧（{activeCount}）
            </button>
            <button
              type='button'
              onClick={() => switchView(true)}
              className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
                trashView
                  ? 'border-blue-900 bg-blue-50 text-blue-900'
                  : 'border-solid-gray-420 text-solid-gray-700'
              }`}
            >
              ゴミ箱（{trashCount}）
            </button>
          </fieldset>
          {isLoading ? (
            <p className='text-solid-gray-600'>読み込み中...</p>
          ) : loadError ? (
            <p className='text-error-1' role='alert'>
              {loadError}
            </p>
          ) : visibleProcs.length === 0 ? (
            <p className='text-solid-gray-600'>
              {trashView ? (
                'ゴミ箱は空です。'
              ) : procedures.length === 0 ? (
                <>
                  まだ手続きがありません。
                  <Link
                    to='/patchform/procedures?tab=new'
                    className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                  >
                    作成タブから作る
                  </Link>
                </>
              ) : (
                '表示できる手続きはありません。'
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
                    <div className='flex flex-wrap items-center gap-2'>
                      <select
                        className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-16N-130'
                        value={bulkAction}
                        onChange={(e) => setBulkAction(e.target.value)}
                        aria-label='一括処理を選ぶ'
                      >
                        <option value=''>一括処理を選ぶ…</option>
                        <option value='close'>受付を終了する</option>
                        <option value='archive'>ゴミ箱へ移す</option>
                      </select>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        aria-disabled={submitting || selectedCount === 0 || !bulkAction}
                        onClick={() => void runBulk()}
                      >
                        {submitting ? '処理中...' : '実行'}
                      </Button>
                    </div>
                  )}
                </div>
              ) : null}
              {bulkResult ? (
                <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
                  {bulkResult}
                </p>
              ) : null}
              <p className='text-dns-14N-130 text-solid-gray-600'>
                {trashView
                  ? '削除は「ゴミ箱へ移す」で退避してから、ここで完全に削除します。申請のある手続きは完全削除できません。'
                  : '削除は「ゴミ箱へ移す」で退避します。公開中の手続きは先に受付を終了してください。'}
              </p>
              <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                {visibleProcs.map((p) => (
                  <li key={p.id} className='flex items-start gap-3 py-3'>
                    {p.can_edit ? (
                      <input
                        type='checkbox'
                        className='mt-0.5 size-5 flex-none'
                        checked={selected.has(p.id)}
                        onChange={() => toggleOne(p.id)}
                        aria-label={`「${p.name}」を選択`}
                      />
                    ) : (
                      <span className='mt-0.5 size-5 flex-none' aria-hidden='true' />
                    )}
                    <div className='min-w-0 flex-1'>
                      {trashView ? (
                        <span className='text-std-16B-150 text-solid-gray-800'>{p.name}</span>
                      ) : (
                        <Link
                          to={`/patchform/procedures/${p.id}`}
                          className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                        >
                          {p.name}
                        </Link>
                      )}
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        {statusLabel[p.status] || p.status}
                        {p.guide_title
                          ? ` / ${omitsNavigation(p) ? '申請フォーム' : '案内'}: ${p.guide_title}`
                          : ''}
                        {' / '}
                        {new Date(p.updated_at).toLocaleString('ja-JP')}
                      </p>
                      {trashView ? null : (
                        <div className='mt-2'>
                          <ProcedureReceptionActions
                            procedureId={p.id}
                            name={p.name}
                            status={p.status}
                            publicUrl={p.status === 'published' ? p.guide_public_url : null}
                            canEdit={p.can_edit}
                            submitting={submitting}
                            republish={p.guide_status === 'closed'}
                            onPublish={async () => {
                              const next = await setStatus(p.id, 'published');
                              if (next) await mutate();
                            }}
                            onClose={async () => {
                              if (
                                !window.confirm(
                                  '受付を終了しますか。新しい申請は止まります。届いている申請は残ります。',
                                )
                              ) {
                                return;
                              }
                              const next = await setStatus(p.id, 'draft');
                              if (next) await mutate();
                            }}
                          />
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
        )}
      </div>
    </LayoutBody>
  );
};
