import { useEffect, useState, type FormEvent, type ComponentType } from 'react';
import {
  PiBookOpenBold,
  PiCheckSquareBold,
  PiFilesBold,
  PiGaugeBold,
  PiLayoutBold,
  PiScalesBold,
  PiTrophyBold,
  PiUploadSimpleBold,
} from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { DoccheckFilePicker } from './DoccheckFilePicker';
import { RegionEditor, regionsFromEditor } from './RegionEditor';
import type {
  BatchSummary,
  CheckTask,
  DoccheckOcrMode,
  DocumentDetail,
  FormTemplate,
  RegionTemplate,
} from './types';

const OCR_MODE_OPTIONS: Array<{ value: DoccheckOcrMode; label: string; hint: string }> = [
  { value: 'ppocr', label: 'PP-OCR のみ', hint: 'Vision を使わない（最速・低コスト）' },
  {
    value: 'fallback',
    label: 'Vision 補完（低信頼のみ）',
    hint: 'PP-OCR が空／低信頼のときだけ Vision を呼ぶ（既定）',
  },
  {
    value: 'always',
    label: '常に両方',
    hint: 'PP-OCR と Vision を毎回実行し、両方を候補表示',
  },
];

const OCR_MODE_BADGE: Record<DoccheckOcrMode, string> = {
  ppocr: 'Vision: 使わない',
  fallback: 'Vision: 補完',
  always: 'Vision: 併用',
};
import {
  fileToBase64,
  useDoccheckActions,
  useDoccheckArbitration,
  useDoccheckBatches,
  useDoccheckConfig,
  useDoccheckDocuments,
  useDoccheckScore,
  useDoccheckTemplates,
} from './useDoccheck';

type Tab = 'dashboard' | 'templates' | 'upload' | 'batch' | 'check' | 'arbitrate' | 'scores';

const CHOICE_MULTI_SEP = ' | ';

const parseMultiSelection = (value: string): string[] =>
  value
    .split('|')
    .map((s) => s.trim())
    .filter(Boolean);

const toggleMultiSelection = (value: string, label: string): string => {
  const set = parseMultiSelection(value);
  const idx = set.indexOf(label);
  if (idx >= 0) set.splice(idx, 1);
  else set.push(label);
  return set.join(CHOICE_MULTI_SEP);
};

type TabItem = {
  id: Tab;
  label: string;
  description: string;
  icon: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
};

/**
 * 書類領域分割チェック専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["doccheck"] 未起動時は有効化手順を案内する。
 */
export const DoccheckPage = () => {
  const { config, isLoading: configLoading, unavailable, mutate: mutateConfig } =
    useDoccheckConfig();
  const canArbitrate = config?.can_arbitrate === true;
  const { templates, mutate: mutateTemplates } = useDoccheckTemplates();
  const { documents, mutate: mutateDocs } = useDoccheckDocuments();
  const { batches, mutate: mutateBatches } = useDoccheckBatches();
  const { score, leaderboard, mutate: mutateScore } = useDoccheckScore();
  const { items: arbitrationItems, mutate: mutateArb } = useDoccheckArbitration(canArbitrate);
  const actions = useDoccheckActions();

  const [tab, setTab] = useState<Tab>('dashboard');
  const [title, setTitle] = useState('');
  const [templateId, setTemplateId] = useState('demo-template');
  const [files, setFiles] = useState<FileList | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<DocumentDetail | null>(null);
  const [selectedBatch, setSelectedBatch] = useState<BatchSummary | null>(null);
  const [batchName, setBatchName] = useState('');
  const [batchFiles, setBatchFiles] = useState<FileList | null>(null);
  const [pagesPerDoc, setPagesPerDoc] = useState(1);
  const [autoDispatch, setAutoDispatch] = useState(true);
  const [task, setTask] = useState<CheckTask | null>(null);
  const [checkHint, setCheckHint] = useState<string | null>(null);
  const [answer, setAnswer] = useState('');
  const [unreadable, setUnreadable] = useState(false);
  const [blank, setBlank] = useState(false);
  const [templateView, setTemplateView] = useState<'list' | 'edit'>('list');
  const [editingTemplate, setEditingTemplate] = useState<FormTemplate | null>(null);
  const [draftRegions, setDraftRegions] = useState<RegionTemplate[]>([]);
  const [draftOcrMode, setDraftOcrMode] = useState<DoccheckOcrMode>('fallback');
  const [editorKey, setEditorKey] = useState(0);
  const [sampleFile, setSampleFile] = useState<FileList | null>(null);
  const [exportJson, setExportJson] = useState<string | null>(null);
  const [exportFileName, setExportFileName] = useState('doccheck-export.json');
  const [newTemplateName, setNewTemplateName] = useState('');

  const refreshDashboardStats = async () => {
    await Promise.all([
      mutateConfig(),
      mutateDocs(),
      canArbitrate ? mutateArb() : Promise.resolve(),
    ]);
  };

  useEffect(() => {
    if (tab !== 'dashboard' || unavailable) return;
    void refreshDashboardStats();
    // ダッシュボード表示時に件数を取り直す
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tab 切替トリガ
  }, [tab]);

  const statusLabel = (status: string) =>
    (
      ({
        ready: '配信待ち',
        processing: '処理中',
        dispatched: 'チェック中',
        completed: '完了',
        needs_arbitration: '裁定待ち',
        error: 'エラー',
      }) as Record<string, string>
    )[status] || status;

  const downloadTextFile = (text: string, filename: string, mime = 'application/json') => {
    const blob = new Blob([text], { type: `${mime};charset=utf-8` });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  };

  const onUpload = async (e: FormEvent) => {
    e.preventDefault();
    actions.setError(null);
    if (!templateId || !files?.length) {
      actions.setError('テンプレートと画像を指定してください');
      return;
    }
    const pages: string[] = [];
    for (const f of Array.from(files)) {
      pages.push(await fileToBase64(f));
    }
    const doc = await actions.createDocument({
      template_id: templateId,
      title: title.trim() || files[0].name,
      pages,
      auto_dispatch: true,
      assignees: 1,
    });
    if (doc) {
      setSelectedDoc(doc);
      await refreshDashboardStats();
      setTab('dashboard');
    }
  };

  const onDispatch = async (docId: string) => {
    const doc = await actions.dispatch(docId);
    if (doc) {
      setSelectedDoc(doc);
      await refreshDashboardStats();
    }
  };

  const onDeleteDoc = async (docId: string, title: string) => {
    if (
      !window.confirm(
        `書類「${title}」を削除します。\n関連するチェックタスク・画像も消え、取り消せません。`,
      )
    ) {
      return;
    }
    const typed = window.prompt(
      '誤削除防止のため、削除する書類のタイトルをそのまま入力してください。',
      '',
    );
    if (typed === null) return;
    if (typed.trim() !== title) {
      actions.setError('タイトルが一致しないため削除しませんでした');
      return;
    }
    const res = await actions.deleteDocument(docId);
    if (res) {
      if (selectedDoc?.id === docId) setSelectedDoc(null);
      if (exportJson) setExportJson(null);
      await mutateBatches();
      await refreshDashboardStats();
    }
  };

  const onDeleteBatch = async (batchId: string, name: string) => {
    if (
      !window.confirm(
        `バッチ「${name}」と配下の全書類を削除します。\nこの操作は取り消せません。`,
      )
    ) {
      return;
    }
    const typed = window.prompt(
      '誤削除防止のため、削除するバッチ名をそのまま入力してください。',
      '',
    );
    if (typed === null) return;
    if (typed.trim() !== name) {
      actions.setError('バッチ名が一致しないため削除しませんでした');
      return;
    }
    const res = await actions.deleteBatch(batchId);
    if (res) {
      if (selectedBatch?.id === batchId) setSelectedBatch(null);
      await mutateBatches();
      await refreshDashboardStats();
    }
  };

  const onLoadDoc = async (docId: string) => {
    const doc = await actions.getDocument(docId);
    if (doc) setSelectedDoc(doc);
  };

  const onExport = async (docId: string, title: string) => {
    const data = await actions.exportDocument(docId);
    if (!data) return;
    const text = JSON.stringify(data, null, 2);
    const safe = title.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80) || 'document';
    const filename = `${safe}.json`;
    setExportJson(text);
    setExportFileName(filename);
    // 単件はプレビューと同時に JSON ファイルをダウンロード
    downloadTextFile(text, filename);
  };

  const onNextCheck = async () => {
    setCheckHint(null);
    const res = await actions.nextTask();
    if (!res) return;
    if (!res.task) {
      setTask(null);
      // キュー空はエラーではなくチェックタブ内の案内のみ（他タブに残さない）
      setCheckHint(res.message || '未処理のタスクはありません');
      await mutateConfig();
      return;
    }
    setTask(res.task);
    const isChoice =
      res.task.field_type === 'choice' || res.task.field_type === 'choice_multi';
    setAnswer(isChoice ? '' : res.task.ocr_text || '');
    setUnreadable(false);
    setBlank(false);
    await mutateConfig();
  };

  const onSubmitCheck = async () => {
    if (!task?.token) return;
    const res = await actions.answerTask(task.token, {
      answer_text: answer,
      is_unreadable: unreadable,
      is_blank: blank,
    });
    if (res) {
      setTask(null);
      await mutateScore();
      await mutateArb();
      await mutateConfig();
      await onNextCheck();
    }
  };

  const onBatchUpload = async (e: FormEvent) => {
    e.preventDefault();
    actions.setError(null);
    if (!templateId || !batchFiles?.length) {
      actions.setError('テンプレートと連続スキャン画像を指定してください');
      return;
    }
    if (batchFiles.length % pagesPerDoc !== 0) {
      actions.setError(
        `画像枚数 (${batchFiles.length}) が「1件あたりページ数」(${pagesPerDoc}) で割り切れません`,
      );
      return;
    }
    const images: Array<{ data: string; name: string }> = [];
    for (const f of Array.from(batchFiles)) {
      images.push({ data: await fileToBase64(f), name: f.name });
    }
    const batch = await actions.createBatch({
      name: batchName.trim() || `連続スキャン ${new Date().toLocaleString('ja-JP')}`,
      template_id: templateId,
      images,
      pages_per_document: pagesPerDoc,
      auto_dispatch: autoDispatch,
      // 未指定 → サーバ側で本番想定 3（DOCCHECK_ASSIGNEES）
    });
    if (batch) {
      setSelectedBatch(batch);
      await mutateBatches();
      await refreshDashboardStats();
    }
  };

  const onRefreshBatch = async (batchId: string) => {
    const b = await actions.getBatch(batchId);
    if (b) setSelectedBatch(b);
    await mutateBatches();
  };

  const onCreateTemplate = async (e: FormEvent) => {
    e.preventDefault();
    if (!newTemplateName.trim()) return;
    const tmpl = await actions.createTemplate({
      name: newTemplateName.trim(),
      description: '手動作成',
      regions: [],
    });
    if (tmpl) {
      setNewTemplateName('');
      setTemplateId(tmpl.id);
      await mutateTemplates();
      await openTemplateEditor(tmpl.id);
      setTab('templates');
    }
  };

  const openTemplateEditor = async (id: string) => {
    const tmpl = await actions.getTemplate(id, true);
    if (!tmpl) return;
    setEditingTemplate(tmpl);
    setDraftRegions(tmpl.regions ?? []);
    setDraftOcrMode(tmpl.ocr_mode ?? 'fallback');
    setSampleFile(null);
    setEditorKey((k) => k + 1);
    setTemplateView('edit');
  };

  const backToTemplateList = () => {
    setTemplateView('list');
    setSampleFile(null);
  };

  const onSampleFileChange = async (files: FileList | null) => {
    setSampleFile(files);
    if (!editingTemplate || !files?.[0]) return;
    actions.setError(null);
    const data = await fileToBase64(files[0]);
    const tmpl = await actions.uploadSample(editingTemplate.id, data);
    if (tmpl) {
      setEditingTemplate(tmpl);
      setDraftRegions(tmpl.regions ?? draftRegions);
      setSampleFile(null);
      setEditorKey((k) => k + 1);
      await mutateTemplates();
    }
  };

  const onSaveRegions = async () => {
    if (!editingTemplate) return;
    let tmpl = await actions.saveRegions(
      editingTemplate.id,
      regionsFromEditor(draftRegions),
    );
    if (tmpl && draftOcrMode !== (tmpl.ocr_mode ?? 'fallback')) {
      const updated = await actions.updateTemplateMeta(editingTemplate.id, {
        ocr_mode: draftOcrMode,
      });
      if (updated) tmpl = updated;
    }
    if (tmpl) {
      setEditingTemplate({
        ...tmpl,
        sample_image_data_url: editingTemplate.sample_image_data_url,
      });
      setDraftRegions(tmpl.regions ?? []);
      setDraftOcrMode(tmpl.ocr_mode ?? 'fallback');
      setEditorKey((k) => k + 1);
      await mutateTemplates();
    }
  };

  const onDeleteTemplate = async () => {
    if (!editingTemplate) return;
    const { id, name } = editingTemplate;
    if (id === 'demo-template') {
      actions.setError('デモテンプレートは削除できません');
      return;
    }
    if (
      !window.confirm(
        `テンプレート「${name}」を削除します。\n領域定義と見本画像も消え、取り消せません。`,
      )
    ) {
      return;
    }
    const typed = window.prompt(
      '誤削除防止のため、削除するテンプレート名をそのまま入力してください。',
      '',
    );
    if (typed === null) return;
    if (typed.trim() !== name) {
      actions.setError('テンプレート名が一致しないため削除しませんでした');
      return;
    }
    const res = await actions.deleteTemplate(id);
    if (res) {
      setEditingTemplate(null);
      setDraftRegions([]);
      setTemplateView('list');
      if (templateId === id) setTemplateId('demo-template');
      await mutateTemplates();
    }
  };

  const tabs: TabItem[] = [
    {
      id: 'dashboard',
      label: 'ダッシュボード',
      description: '件数・書類一覧',
      icon: PiGaugeBold,
    },
    {
      id: 'templates',
      label: 'テンプレート',
      description: '領域を定義',
      icon: PiLayoutBold,
    },
    {
      id: 'upload',
      label: '読み取りテスト',
      description: '1件で動作確認',
      icon: PiUploadSimpleBold,
    },
    {
      id: 'batch',
      label: 'バッチ',
      description: '連続スキャン',
      icon: PiFilesBold,
    },
    {
      id: 'check',
      label: 'チェック',
      description: '庁内キュー',
      icon: PiCheckSquareBold,
    },
    ...(canArbitrate
      ? [
          {
            id: 'arbitrate' as const,
            label: '裁定',
            description: '不一致を確定',
            icon: PiScalesBold,
          },
        ]
      : []),
    {
      id: 'scores',
      label: 'スコア',
      description: '累計ポイント',
      icon: PiTrophyBold,
    },
  ];

  useEffect(() => {
    if (!canArbitrate && tab === 'arbitrate') {
      setTab('dashboard');
    }
  }, [canArbitrate, tab]);

  return (
    <LayoutBody>
      <PageTitle title='書類チェック' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <div className='flex flex-col gap-4'>
          <BreadcrumbsNav
            items={[
              { label: 'ホーム', to: '/' },
              { label: 'AIアプリ', to: '/apps' },
              { label: '書類チェック' },
            ]}
          />
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>書類チェック</h1>
          <p className='text-std-16N-170 text-solid-gray-700'>
            申請書類を領域分割し、OCR 候補と画像を分散チェックして補正データを作ります。外部公開は別ホストの
            /public のみです。
          </p>
          <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
            <DisclosureSummary>
              <span className='flex items-center text-std-16B-150'>
                <PiBookOpenBold className='mr-2 size-5 flex-none' />
                使い方（クリックで開閉）
              </span>
            </DisclosureSummary>
            <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
              <p>・帳票テンプレートの領域（正規化座標）に沿ってスキャン画像を切り出します。</p>
              <p>・配信後、庁内キューと外部トークン URL でチェックできます。</p>
              <p>
                ・有効化: <code>docker compose --profile doccheck up -d</code> または{' '}
                <code>COMPOSE_PROFILES=doccheck</code>
              </p>
              <p>
                ・OCR 既定: Vision LLM（
                {config?.ocr_engine || 'vision'}
                ）。手書き読取後も人間チェック前提です。
              </p>
              <p>・投入時に画像を OCR 向けへ正規化（グレー・長辺リサイズ）。読み取りテストは割当1、バッチは割当3。</p>
              {config?.public_endpoint && (
                <p>・外部公開 endpoint: {config.public_endpoint}</p>
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
              書類チェックは現在有効化されていません
            </p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error || 'コンテナを profiles: ["doccheck"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile doccheck up -d{'\n'}
              # または .env に COMPOSE_PROFILES=doccheck
            </pre>
          </div>
        )}

        {!unavailable && (
          <>
            <div
              className='grid grid-cols-[repeat(auto-fit,minmax(calc(140/16*1rem),1fr))] gap-2'
              role='tablist'
              aria-label='書類チェックの操作'
            >
              {tabs.map((t) => {
                const selected = tab === t.id;
                const Icon = t.icon;
                return (
                  <button
                    key={t.id}
                    type='button'
                    role='tab'
                    aria-selected={selected}
                    onClick={() => {
                      actions.setError(null);
                      setCheckHint(null);
                      if (t.id === 'templates') {
                        setTemplateView('list');
                      }
                      setTab(t.id);
                    }}
                    className={`flex flex-col items-center gap-1 rounded-8 border px-2 pt-3 pb-3 text-center hover:border-transparent hover:bg-solid-gray-50 hover:outline-2 hover:outline-black hover:outline-solid lg:px-3 ${
                      selected
                        ? 'border-blue-900 bg-blue-50'
                        : 'border-solid-gray-420 bg-white'
                    }`}
                  >
                    <Icon
                      aria-hidden={true}
                      className='size-6 text-solid-gray-900'
                    />
                    <span className='text-dns-16B-130 text-pretty text-solid-gray-900'>
                      {t.label}
                    </span>
                    <span className='text-dns-14N-130 text-pretty text-solid-gray-700'>
                      {t.description}
                    </span>
                  </button>
                );
              })}
            </div>

            {actions.error && (
              <p className='text-std-16N-170 text-red-700' role='alert'>
                {actions.error}
              </p>
            )}

            {tab === 'dashboard' && (
              <section className='flex flex-col gap-4'>
                <div className='grid gap-3 sm:grid-cols-3'>
                  <Stat label='書類数' value={documents.length} />
                  <Stat
                    label='未処理タスク'
                    value={config?.pending_tasks ?? '-'}
                  />
                  <Stat
                    label='裁定待ち'
                    value={
                      canArbitrate
                        ? arbitrationItems.length
                        : (config?.arbitration_count ?? '-')
                    }
                  />
                </div>
                <p className='text-std-14N-170 text-solid-gray-700'>
                  OCR: {config?.ocr_engine || 'hybrid'}
                  {config?.ppocr_backend ? `（PP-OCR: ${config.ppocr_backend}` : ''}
                  {config?.official_paddleocr_available != null
                    ? ` / 本家=${config.official_paddleocr_available ? 'あり' : 'なし'}`
                    : ''}
                  {config?.ppocr_backend ? '）' : ''} ／ 割当: テスト
                  {config?.single_assignees_default ?? 1}・バッチ
                  {config?.batch_assignees_default ?? config?.assignees_default ?? 3}
                  {config?.ocr_normalize === false ? '' : ' ／ 画像正規化ON'}
                </p>
                <div>
                  <h2 className='text-std-18B-160'>書類一覧</h2>
                  {documents.length > 0 && (
                    <p className='mt-1 text-std-14N-170 text-solid-gray-700'>
                      「進捗を見る」で領域と外部URLを確認。「JSONダウンロード」で結果ファイルを取得（画面にも表示）。「削除…」はタイトル再入力が必要です。
                    </p>
                  )}
                </div>
                <ul className='flex flex-col gap-2'>
                  {documents.map((d) => (
                    <li
                      key={d.id}
                      className='flex flex-col gap-2 rounded-8 border border-solid-gray-420 px-4 py-3 sm:flex-row sm:items-center sm:justify-between'
                    >
                      <div>
                        <p className='text-std-16B-150'>{d.title}</p>
                        <p className='text-std-14N-170 text-solid-gray-700'>
                          {d.template_name} · {statusLabel(d.status)}
                        </p>
                      </div>
                      <div className='flex flex-wrap gap-2'>
                        <Button
                          type='button'
                          size='sm'
                          variant='outline'
                          title='領域進捗・外部チェックURLを表示'
                          onClick={() => onLoadDoc(d.id)}
                        >
                          進捗を見る
                        </Button>
                        {d.status === 'ready' && (
                          <Button
                            type='button'
                            size='sm'
                            variant='solid-fill'
                            aria-disabled={actions.submitting || undefined}
                            title='チェッカーへタスクを配信'
                            onClick={() => onDispatch(d.id)}
                          >
                            チェック配信
                          </Button>
                        )}
                        <Button
                          type='button'
                          size='sm'
                          variant='outline'
                          title='確定結果を JSON でダウンロード（下にプレビューも表示）'
                          onClick={() => onExport(d.id, d.title)}
                        >
                          JSONダウンロード
                        </Button>
                        <Button
                          type='button'
                          size='sm'
                          variant='outline'
                          aria-disabled={actions.submitting || undefined}
                          title='書類と関連データを完全削除（要タイトル確認）'
                          onClick={() => onDeleteDoc(d.id, d.title)}
                        >
                          削除…
                        </Button>
                      </div>
                    </li>
                  ))}
                  {documents.length === 0 && (
                    <li className='text-solid-gray-700'>
                      まだ書類がありません。「テンプレート」で領域を定義し、「読み取りテスト」または「バッチ」から登録してください。
                    </li>
                  )}
                </ul>
                {selectedDoc && (
                  <div className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
                    <h3 className='text-std-16B-150'>{selectedDoc.title}</h3>
                    <p className='text-std-14N-170 text-solid-gray-700'>
                      状態: {statusLabel(selectedDoc.status)} ／ 領域:{' '}
                      {selectedDoc.regions?.length ?? 0}
                    </p>
                    {selectedDoc.tasks && selectedDoc.tasks.length > 0 && (
                      <div className='mt-2'>
                        <p className='text-std-14B-150'>外部チェック URL（先頭 5 件）</p>
                        <ul className='mt-1 flex flex-col gap-1 text-dns-14N-130'>
                          {selectedDoc.tasks
                            .filter((t) => t.tier === 'external')
                            .slice(0, 5)
                            .map((t) => (
                              <li key={t.id} className='break-all'>
                                {t.public_url}
                              </li>
                            ))}
                        </ul>
                        <p className='mt-2 text-std-14N-170 text-solid-gray-700'>
                          まとめて試す:{' '}
                          <a
                            className='underline'
                            href={`${config?.public_endpoint || 'http://localhost:8011'}/public/`}
                            target='_blank'
                            rel='noreferrer'
                          >
                            公開トップ（次の1件）
                          </a>
                        </p>
                      </div>
                    )}
                  </div>
                )}
                {exportJson && (
                  <div className='rounded-8 border border-solid-gray-420 px-4 py-3'>
                    <div className='flex flex-wrap items-center justify-between gap-2'>
                      <h3 className='text-std-16B-150'>出力プレビュー（JSON）</h3>
                      <Button
                        type='button'
                        size='sm'
                        variant='solid-fill'
                        onClick={() => downloadTextFile(exportJson, exportFileName)}
                      >
                        もう一度ダウンロード
                      </Button>
                    </div>
                    <p className='mt-1 text-std-14N-170 text-solid-gray-700'>
                      ボタン押下時にファイル（{exportFileName}）のダウンロードも開始しています。バッチの大量出力は「バッチ」タブの CSV / JSONL を使います。
                    </p>
                    <pre className='mt-3 max-h-96 overflow-auto rounded-8 bg-white p-3 text-dns-14N-130'>
                      {exportJson}
                    </pre>
                  </div>
                )}
              </section>
            )}

            {tab === 'batch' && (
              <section className='flex flex-col gap-6'>
                <form onSubmit={onBatchUpload} className='flex flex-col gap-4'>
                  <h2 className='text-std-18B-160'>連続スキャン一括投入</h2>
                  <p className='text-std-14N-170 text-solid-gray-700'>
                    同じ様式のスキャン画像をまとめて投入します（例: 500件）。処理はバックグラウンドで進み、完了分から CSV /
                    JSONL で出力できます。
                  </p>
                  <div>
                    <Label htmlFor='dc-batch-name' size='sm'>
                      バッチ名
                    </Label>
                    <input
                      id='dc-batch-name'
                      className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={batchName}
                      onChange={(e) => setBatchName(e.target.value)}
                      placeholder='例: 2026-08-11 午前受付分'
                    />
                  </div>
                  <div>
                    <Label htmlFor='dc-batch-tmpl' size='sm'>
                      帳票テンプレート
                    </Label>
                    <select
                      id='dc-batch-tmpl'
                      className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={templateId}
                      onChange={(e) => setTemplateId(e.target.value)}
                    >
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label htmlFor='dc-ppd' size='sm'>
                      1件あたりページ数
                    </Label>
                    <input
                      id='dc-ppd'
                      type='number'
                      min={1}
                      className='mt-1 w-40 rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={pagesPerDoc}
                      onChange={(e) => setPagesPerDoc(Number(e.target.value) || 1)}
                    />
                    <p className='mt-1 text-std-14N-170 text-solid-gray-700'>
                      チェック割当は本番想定の {config?.batch_assignees_default ?? 3}{' '}
                      人固定。画像は投入時に OCR 向けへ自動正規化します。
                    </p>
                  </div>
                  <label className='flex items-center gap-2 text-std-14N-170'>
                    <input
                      type='checkbox'
                      checked={autoDispatch}
                      onChange={(e) => setAutoDispatch(e.target.checked)}
                    />
                    投入後に自動でチェック配信する
                  </label>
                  <DoccheckFilePicker
                    id='dc-batch-files'
                    label='スキャン画像（複数・ファイル名順を推奨）'
                    multiple
                    disabled={actions.submitting}
                    files={batchFiles}
                    onChange={setBatchFiles}
                  />
                  {batchFiles && batchFiles.length > 0 && (
                    <p className='text-std-14N-170 text-solid-gray-700'>
                      {batchFiles.length} 枚 → 約{' '}
                      {Math.floor(batchFiles.length / pagesPerDoc)} 件
                    </p>
                  )}
                  <Button
                    type='submit'
                    size='md'
                    variant='solid-fill'
                    aria-disabled={actions.submitting || undefined}
                  >
                    {actions.submitting ? '投入中…' : 'バッチ投入を開始'}
                  </Button>
                </form>

                <div>
                  <h3 className='text-std-16B-150'>バッチ一覧</h3>
                  <ul className='mt-2 flex flex-col gap-2'>
                    {batches.map((b) => (
                      <li
                        key={b.id}
                        className='rounded-8 border border-solid-gray-420 px-4 py-3'
                      >
                        <div className='flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'>
                          <div>
                            <p className='text-std-16B-150'>{b.name}</p>
                            <p className='text-std-14N-170 text-solid-gray-700'>
                              {b.template_name} · {b.status} · 処理{' '}
                              {b.processed_documents}/{b.total_documents}
                              {b.progress
                                ? ` · 完了 ${b.progress.completed} / 裁定待ち ${b.progress.needs_arbitration}`
                                : ''}
                            </p>
                          </div>
                          <div className='flex flex-wrap gap-2'>
                            <Button
                              type='button'
                              size='sm'
                              variant='outline'
                              onClick={() => onRefreshBatch(b.id)}
                            >
                              詳細更新
                            </Button>
                            <Button
                              type='button'
                              size='sm'
                              variant='solid-fill'
                              onClick={() => actions.downloadBatchExport(b.id, 'csv', 'completed')}
                            >
                              CSV出力
                            </Button>
                            <Button
                              type='button'
                              size='sm'
                              variant='outline'
                              onClick={() => actions.downloadBatchExport(b.id, 'jsonl', 'completed')}
                            >
                              JSONL
                            </Button>
                            <Button
                              type='button'
                              size='sm'
                              variant='outline'
                              disabled={actions.submitting}
                              onClick={() => onDeleteBatch(b.id, b.name)}
                            >
                              削除…
                            </Button>
                          </div>
                        </div>
                      </li>
                    ))}
                    {batches.length === 0 && (
                      <li className='text-solid-gray-700'>まだバッチがありません。</li>
                    )}
                  </ul>
                </div>

                {selectedBatch && (
                  <div className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
                    <h3 className='text-std-16B-150'>{selectedBatch.name}</h3>
                    <p className='mt-1 text-std-14N-170 text-solid-gray-700'>
                      進捗: 完了 {selectedBatch.progress?.completed ?? 0} / 全体{' '}
                      {selectedBatch.progress?.total ?? selectedBatch.total_documents}
                      （裁定待ち {selectedBatch.progress?.needs_arbitration ?? 0}）
                    </p>
                    {selectedBatch.last_error && (
                      <p className='mt-1 text-std-14N-170 text-red-700'>
                        直近エラー: {selectedBatch.last_error}
                      </p>
                    )}
                    <div className='mt-3 flex flex-wrap gap-2'>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        onClick={() =>
                          actions.downloadBatchExport(selectedBatch.id, 'csv', 'completed')
                        }
                      >
                        完了分 CSV
                      </Button>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        onClick={() =>
                          actions.downloadBatchExport(selectedBatch.id, 'jsonl', 'completed')
                        }
                      >
                        完了分 JSONL
                      </Button>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        onClick={() =>
                          actions.downloadBatchExport(selectedBatch.id, 'csv', 'all')
                        }
                      >
                        全件 CSV
                      </Button>
                      <Button
                        type='button'
                        size='sm'
                        variant='solid-fill'
                        disabled={actions.submitting}
                        onClick={async () => {
                          const b = await actions.dispatchBatch(selectedBatch.id);
                          if (b) setSelectedBatch(b);
                          await mutateBatches();
                          await refreshDashboardStats();
                        }}
                      >
                        未配信を一括配信
                      </Button>
                    </div>
                  </div>
                )}
              </section>
            )}

            {tab === 'templates' && templateView === 'list' && (
              <section className='flex flex-col gap-4'>
                <div>
                  <h2 className='text-std-18B-160'>帳票テンプレート一覧</h2>
                  <p className='mt-1 text-std-14N-170 text-solid-gray-700'>
                    テンプレートを選んで領域を編集します。新規作成もここから行えます。
                  </p>
                </div>

                <form
                  onSubmit={onCreateTemplate}
                  className='flex flex-col gap-2 rounded-8 border border-solid-gray-420 p-4 sm:flex-row sm:items-end'
                >
                  <div className='flex-1'>
                    <Label htmlFor='dc-new-tmpl-tab' size='sm'>
                      新規テンプレート名
                    </Label>
                    <input
                      id='dc-new-tmpl-tab'
                      className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={newTemplateName}
                      onChange={(e) => setNewTemplateName(e.target.value)}
                      placeholder='例: 補助金申請書A'
                    />
                  </div>
                  <Button
                    type='submit'
                    size='md'
                    variant='solid-fill'
                    aria-disabled={actions.submitting || undefined}
                  >
                    作成して編集
                  </Button>
                </form>

                <ul className='flex flex-col gap-2'>
                  {templates.map((t) => (
                    <li
                      key={t.id}
                      className='flex flex-col gap-2 rounded-8 border border-solid-gray-420 px-4 py-3 sm:flex-row sm:items-center sm:justify-between'
                    >
                      <div>
                        <p className='text-std-16B-150'>{t.name}</p>
                        <p className='text-std-14N-170 text-solid-gray-700'>
                          領域 {t.region_count ?? t.regions?.length ?? 0} 件
                          {` · ${OCR_MODE_BADGE[t.ocr_mode ?? 'fallback']}`}
                          {t.id === 'demo-template' ? ' · デモ' : ''}
                          {t.description ? ` · ${t.description}` : ''}
                        </p>
                      </div>
                      <Button
                        type='button'
                        size='md'
                        variant='outline'
                        onClick={() => void openTemplateEditor(t.id)}
                      >
                        編集する
                      </Button>
                    </li>
                  ))}
                  {templates.length === 0 && (
                    <li className='text-solid-gray-700'>
                      テンプレートがありません。上のフォームから作成してください。
                    </li>
                  )}
                </ul>
              </section>
            )}

            {tab === 'templates' && templateView === 'edit' && editingTemplate && (
              <section className='flex flex-col gap-4'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <div>
                    <Button
                      type='button'
                      size='sm'
                      variant='text'
                      onClick={backToTemplateList}
                    >
                      ← テンプレート一覧に戻る
                    </Button>
                    <h2 className='mt-2 text-std-18B-160'>{editingTemplate.name}</h2>
                    <p className='mt-1 text-std-14N-170 text-solid-gray-700'>
                      見本画像上に矩形を置き、OCR／チェック対象領域を定義します（オーバーラップ余白は自動）。
                    </p>
                    <label className='mt-3 flex flex-col gap-1 text-std-14N-170 text-solid-gray-700'>
                      <span className='font-bold'>OCR モード（帳票全体）</span>
                      <select
                        className='w-fit rounded border border-solid-gray-420 bg-white px-2 py-1 text-std-14N-170'
                        value={draftOcrMode}
                        disabled={actions.submitting}
                        onChange={(e) =>
                          setDraftOcrMode(e.target.value as DoccheckOcrMode)
                        }
                      >
                        {OCR_MODE_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                      <span className='text-std-12N-170 text-solid-gray-600'>
                        {OCR_MODE_OPTIONS.find((o) => o.value === draftOcrMode)?.hint}
                        {'　選択項目・トラップは Vision を呼びません。'}
                      </span>
                    </label>
                  </div>
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      type='button'
                      size='md'
                      variant='outline'
                      aria-disabled={actions.submitting || undefined}
                      title='テンプレートを削除（参照中の書類がある場合は不可）'
                      onClick={() => void onDeleteTemplate()}
                    >
                      テンプレート削除…
                    </Button>
                    <Button
                      type='button'
                      size='md'
                      variant='solid-fill'
                      aria-disabled={actions.submitting || undefined}
                      onClick={() => void onSaveRegions()}
                    >
                      {actions.submitting ? '保存中…' : '領域を保存'}
                    </Button>
                  </div>
                </div>

                <DoccheckFilePicker
                  id='dc-sample'
                  label='見本画像（下絵）'
                  buttonLabel={
                    actions.submitting ? 'アップロード中…' : '見本をアップロード'
                  }
                  disabled={actions.submitting}
                  files={sampleFile}
                  onChange={(f) => void onSampleFileChange(f)}
                />

                <RegionEditor
                  key={editorKey}
                  imageUrl={editingTemplate.sample_image_data_url || null}
                  initialRegions={draftRegions}
                  maxRegions={editingTemplate.max_regions ?? 50}
                  disabled={actions.submitting}
                  onChange={setDraftRegions}
                />
              </section>
            )}

            {tab === 'upload' && (
              <section className='flex flex-col gap-6'>
                <form onSubmit={onUpload} className='flex flex-col gap-4'>
                  <h2 className='flex items-center gap-2 text-std-18B-160'>
                    <PiCheckSquareBold className='size-5' />
                    読み取りテスト
                  </h2>
                  <p className='text-std-14N-170 text-solid-gray-700'>
                    テンプレートと領域の動作確認用です。投入時に画像を OCR
                    向けへ正規化し、割当1人で自動配信します。本番の連続処理は「バッチ」を使ってください。
                  </p>
                  <div>
                    <Label htmlFor='dc-title' size='sm'>
                      タイトル
                    </Label>
                    <input
                      id='dc-title'
                      className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                    />
                  </div>
                  <div>
                    <Label htmlFor='dc-tmpl' size='sm'>
                      帳票テンプレート
                    </Label>
                    <select
                      id='dc-tmpl'
                      className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={templateId}
                      onChange={(e) => setTemplateId(e.target.value)}
                    >
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}（領域 {t.region_count ?? t.regions?.length ?? 0}）
                        </option>
                      ))}
                    </select>
                  </div>
                  <DoccheckFilePicker
                    id='dc-files'
                    label='ページ画像（PNG/JPEG）'
                    multiple
                    disabled={actions.submitting}
                    files={files}
                    onChange={setFiles}
                  />
                  <Button
                    type='submit'
                    size='md'
                    variant='solid-fill'
                    aria-disabled={actions.submitting || undefined}
                  >
                    {actions.submitting ? '処理中…' : 'テスト投入して配信'}
                  </Button>
                </form>

                <p className='text-std-14N-170 text-solid-gray-700'>
                  領域の定義・見本画像の設定は「テンプレート」タブで行います。
                </p>
              </section>
            )}

            {tab === 'check' && (
              <section className='flex flex-col gap-4'>
                <h2 className='text-std-18B-160'>庁内チェックキュー</h2>
                <Button type='button' size='md' variant='solid-fill' onClick={onNextCheck}>
                  次の1件を取得
                </Button>
                {checkHint && !task && (
                  <p className='text-std-16N-170 text-solid-gray-700' role='status'>
                    {checkHint}
                  </p>
                )}
                {task && task.status !== 'done' && (
                  <div className='rounded-8 border border-solid-gray-420 p-4'>
                    <p className='text-std-16B-150'>{task.name}</p>
                    {task.image_data_url && (
                      <img
                        src={task.image_data_url}
                        alt='対象領域'
                        className='mt-3 max-h-64 rounded-8 border border-solid-gray-420 bg-solid-gray-50 object-contain'
                      />
                    )}
                    <p className='mt-2 text-std-14N-170 text-solid-gray-700'>
                      OCR候補（PP-OCR）: {task.ocr_text || '（なし）'}（信頼度{' '}
                      {Number(task.ocr_confidence || 0).toFixed(2)}）
                    </p>
                    {task.ocr_vision_text ? (
                      <p className='text-std-14N-170 text-solid-gray-700'>
                        Vision候補（AI読取）: {task.ocr_vision_text}
                      </p>
                    ) : null}
                    {(task.field_type === 'choice' ||
                      task.field_type === 'choice_multi') &&
                    (task.choice_options?.length ?? 0) > 0 ? (
                      <fieldset
                        className='mt-2'
                        disabled={unreadable || blank}
                        aria-label='選択肢'
                      >
                        <div className='flex flex-col gap-1'>
                          {task.choice_options?.map((opt) => {
                            const multi = task.field_type === 'choice_multi';
                            const checked = multi
                              ? parseMultiSelection(answer).includes(opt)
                              : answer === opt;
                            return (
                              <label
                                key={opt}
                                className='flex items-center gap-2 text-std-14N-170'
                              >
                                <input
                                  type={multi ? 'checkbox' : 'radio'}
                                  name='dc-choice'
                                  checked={checked}
                                  disabled={unreadable || blank}
                                  onChange={() =>
                                    setAnswer(
                                      multi
                                        ? toggleMultiSelection(answer, opt)
                                        : opt,
                                    )
                                  }
                                />
                                {opt}
                              </label>
                            );
                          })}
                        </div>
                      </fieldset>
                    ) : (
                      <>
                        <Label htmlFor='dc-answer' size='sm'>
                          読み取り結果
                        </Label>
                        {task.field_type === 'text_multi' ? (
                          <textarea
                            id='dc-answer'
                            className='mt-1 h-28 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                            value={answer}
                            disabled={unreadable || blank}
                            onChange={(e) => setAnswer(e.target.value)}
                          />
                        ) : (
                          <input
                            id='dc-answer'
                            className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                            value={answer}
                            disabled={unreadable || blank}
                            onChange={(e) => setAnswer(e.target.value)}
                          />
                        )}
                      </>
                    )}
                    {(task.suggestions?.length ?? 0) > 0 && (
                      <div className='mt-2'>
                        <p className='text-std-12N-170 text-solid-gray-700'>
                          補正候補（過去の確定・入力値）
                        </p>
                        <div className='mt-1 flex flex-wrap gap-2'>
                          {task.suggestions?.map((s) => (
                            <button
                              key={s}
                              type='button'
                              disabled={unreadable || blank}
                              className='rounded-8 border border-solid-gray-420 px-2 py-1 text-std-14N-170 hover:bg-blue-50 disabled:opacity-50'
                              onClick={() =>
                                setAnswer(
                                  task.field_type === 'choice_multi'
                                    ? toggleMultiSelection(answer, s)
                                    : s,
                                )
                              }
                            >
                              {s}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className='mt-2 flex flex-wrap gap-4'>
                      <label className='flex items-center gap-2 text-std-14N-170'>
                        <input
                          type='checkbox'
                          checked={blank}
                          onChange={(e) => {
                            setBlank(e.target.checked);
                            if (e.target.checked) setUnreadable(false);
                          }}
                        />
                        空欄（記入なし）
                      </label>
                      <label className='flex items-center gap-2 text-std-14N-170'>
                        <input
                          type='checkbox'
                          checked={unreadable}
                          onChange={(e) => {
                            setUnreadable(e.target.checked);
                            if (e.target.checked) setBlank(false);
                          }}
                        />
                        判読不能
                      </label>
                    </div>
                    <div className='mt-3 flex flex-wrap gap-2'>
                      <Button
                        type='button'
                        size='md'
                        variant='solid-fill'
                        aria-disabled={actions.submitting || undefined}
                        onClick={onSubmitCheck}
                      >
                        送信
                      </Button>
                      {task.field_type !== 'choice' &&
                        task.field_type !== 'choice_multi' && (
                          <Button
                            type='button'
                            size='md'
                            variant='outline'
                            onClick={() => {
                              setAnswer(task.ocr_text || '');
                              setBlank(false);
                              setUnreadable(false);
                            }}
                          >
                            {task.ocr_vision_text
                              ? 'PP-OCR候補を採用'
                              : 'OCR候補を採用'}
                          </Button>
                        )}
                      {task.field_type !== 'choice' &&
                        task.field_type !== 'choice_multi' &&
                        task.ocr_vision_text && (
                          <Button
                            type='button'
                            size='md'
                            variant='outline'
                            onClick={() => {
                              setAnswer(task.ocr_vision_text || '');
                              setBlank(false);
                              setUnreadable(false);
                            }}
                          >
                            Vision候補を採用
                          </Button>
                        )}
                    </div>
                  </div>
                )}
              </section>
            )}

            {tab === 'arbitrate' && (
              <section className='flex flex-col gap-4'>
                <h2 className='text-std-18B-160'>裁定待ち</h2>
                {arbitrationItems.length === 0 && (
                  <p className='text-solid-gray-700'>裁定待ちの項目はありません。</p>
                )}
                {arbitrationItems.map((item) => (
                  <ArbitrationCard
                    key={item.id}
                    item={item}
                    busy={actions.submitting}
                    onAdopt={async (text, isBlank) => {
                      const ok = await actions.arbitrate(item.id, text, isBlank);
                      if (ok) {
                        await mutateArb();
                        await mutateConfig();
                      }
                    }}
                  />
                ))}
              </section>
            )}

            {tab === 'scores' && (
              <section className='flex flex-col gap-4'>
                <h2 className='flex items-center gap-2 text-std-18B-160'>
                  <PiTrophyBold className='size-5' />
                  庁内スコア
                </h2>
                <div className='rounded-8 border border-solid-gray-420 px-4 py-3'>
                  <p className='text-std-16B-150'>あなたのスコア</p>
                  <p className='mt-1 text-std-16N-170'>
                    {score?.points ?? 0} pt ／ チェック {score?.checks_count ?? 0} 件 ／ 採用貢献{' '}
                    {score?.adopted_count ?? 0} 件
                  </p>
                </div>
                <h3 className='text-std-16B-150'>ランキング</h3>
                <ol className='flex flex-col gap-2'>
                  {leaderboard.map((row, i) => (
                    <li
                      key={row.user_id}
                      className='flex justify-between rounded-8 border border-solid-gray-420 px-3 py-2'
                    >
                      <span>
                        {i + 1}. {row.display_name || row.user_id}
                      </span>
                      <span>{row.points} pt</span>
                    </li>
                  ))}
                  {leaderboard.length === 0 && (
                    <li className='text-solid-gray-700'>まだスコアがありません。</li>
                  )}
                </ol>
              </section>
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};

const Stat = ({ label, value }: { label: string; value: string | number }) => (
  <div className='rounded-8 border border-solid-gray-420 px-4 py-3'>
    <p className='text-std-14N-170 text-solid-gray-700'>{label}</p>
    <p className='text-std-20B-160'>{value}</p>
  </div>
);

const ArbitrationCard = ({
  item,
  busy,
  onAdopt,
}: {
  item: {
    id: string;
    name: string;
    document_title?: string;
    ocr_text?: string;
    answers: Array<{
      answer_text: string;
      tier: string;
      is_blank?: boolean | number;
    }>;
  };
  busy: boolean;
  onAdopt: (text: string, isBlank?: boolean) => Promise<void>;
}) => {
  const [text, setText] = useState(item.answers[0]?.answer_text || item.ocr_text || '');
  return (
    <div className='rounded-8 border border-solid-gray-420 p-4'>
      <p className='text-std-16B-150'>{item.name}</p>
      <p className='text-std-14N-170 text-solid-gray-700'>{item.document_title}</p>
      <ul className='mt-2 text-std-14N-170'>
        {item.answers.map((a, i) => (
          <li key={`${a.tier}-${i}`}>
            [{a.tier}] {a.is_blank ? '（空欄）' : a.answer_text || '（空欄）'}
          </li>
        ))}
      </ul>
      <input
        className='mt-2 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className='mt-2 flex flex-wrap gap-2'>
        <Button
          type='button'
          size='sm'
          variant='solid-fill'
          disabled={busy || !text.trim()}
          onClick={() => onAdopt(text.trim())}
        >
          この内容で採用
        </Button>
        <Button
          type='button'
          size='sm'
          variant='outline'
          disabled={busy}
          onClick={() => onAdopt('', true)}
        >
          空欄で確定
        </Button>
      </div>
    </div>
  );
};
