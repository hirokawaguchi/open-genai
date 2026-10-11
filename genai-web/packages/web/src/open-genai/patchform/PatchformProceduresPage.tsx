import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PATCHFORM_LABEL } from './labels';
import { PatchformGuideAssist } from './PatchformGuideAssist';
import { PatchformSubnav } from './PatchformSubnav';
import { ProcedureCreateWizard } from './ProcedureCreateWizard';
import { ProcedureReceptionActions } from './ProcedureReceptionActions';
import { omitsNavigation } from './types';
import {
  downloadProcedurePortable,
  extractPatchformFile,
  readExportBundleFile,
  usePatchformAssist,
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
  const [searchParams, setSearchParams] = useSearchParams();
  const { mutate: mutateForms } = usePatchformList();
  const { procedures, isLoading, loadError, mutate } = usePatchformProcedures();
  const {
    setStatus,
    setStatusMany,
    removeMany,
    importProcedure,
    duplicate: duplicateProcedure,
    submitting,
  } = usePatchformProcedureActions();
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null);
  const {
    previewProcedure,
    applyProcedureDraft,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [assistOpen, setAssistOpen] = useState(false);
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

  useEffect(() => {
    if (searchParams.get('tab') !== 'new') return;
    setWizardOpen(true);
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);

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

  const onExportProcedure = async (id: string) => {
    setImportMsg(null);
    setExportingId(id);
    try {
      await downloadProcedurePortable(id);
    } catch {
      setImportMsg('書き出しに失敗しました。');
    } finally {
      setExportingId(null);
    }
  };

  const onDuplicateProcedure = async (id: string) => {
    setImportMsg(null);
    setDuplicatingId(id);
    try {
      const created = await duplicateProcedure(id);
      if (created) {
        await Promise.all([mutate(), mutateForms()]);
        setImportMsg(`「${created.name}」を複製しました（未公開）。`);
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
      if (bundle.kind !== 'procedure') {
        setImportMsg('これはフォームの書き出しファイルです。フォーム一覧の「読み込み」からお試しください。');
        return;
      }
      const created = await importProcedure(bundle);
      if (created) {
        await Promise.all([mutate(), mutateForms()]);
        setImportMsg(`「${created.name}」を下書きとして取り込みました（構成フォームも作成しました）。`);
      }
    } catch (err) {
      setImportMsg(err instanceof Error ? err.message : '取り込みに失敗しました。');
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
            手続きを公開して、受付可能な状態にします。新しい手続きは「新しい手続きを作る」から始め、できた手続きは編集画面で直します。
          </p>
        </div>

        <section className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h2 className='text-std-18B-160'>手続き一覧</h2>
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
              <Button type='button' variant='outline' size='sm' onClick={() => setAssistOpen(true)}>
                手引きから候補を出す
              </Button>
              <Button type='button' variant='solid-fill' size='sm' onClick={() => setWizardOpen(true)}>
                新しい手続きを作る
              </Button>
            </div>
          </div>
          {importMsg ? (
            <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
              {importMsg}
            </p>
          ) : null}
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
                  <button
                    type='button'
                    className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                    onClick={() => setWizardOpen(true)}
                  >
                    新しい手続きを作る
                  </button>
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
                    {p.can_edit ? (
                      <div className='mt-0.5 flex flex-none gap-2'>
                        <button
                          type='button'
                          className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700 hover:bg-solid-gray-50'
                          aria-disabled={duplicatingId === p.id}
                          onClick={() => void onDuplicateProcedure(p.id)}
                        >
                          {duplicatingId === p.id ? '複製中...' : '複製'}
                        </button>
                        <button
                          type='button'
                          className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700 hover:bg-solid-gray-50'
                          aria-disabled={exportingId === p.id}
                          onClick={() => void onExportProcedure(p.id)}
                        >
                          {exportingId === p.id ? '書き出し中...' : '書き出し'}
                        </button>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
        <ProcedureCreateWizard
          open={wizardOpen}
          onClose={() => setWizardOpen(false)}
          onCreated={async (created) => {
            setWizardOpen(false);
            await mutate();
            navigate(`/patchform/procedures/${created.id}`);
          }}
        />
        <CustomDialog isOpen={assistOpen} onClose={() => setAssistOpen(false)} position='top'>
          <CustomDialogPanel className='max-w-3xl'>
            <CustomDialogHeader hasClose={true} onClose={() => setAssistOpen(false)}>
              手引きから候補を出す
            </CustomDialogHeader>
            <CustomDialogBody>
              <PatchformGuideAssist
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
                  setAssistOpen(false);
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
            </CustomDialogBody>
          </CustomDialogPanel>
        </CustomDialog>
      </div>
    </LayoutBody>
  );
};
