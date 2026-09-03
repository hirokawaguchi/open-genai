import MDEditor from '@uiw/react-md-editor';
import * as commands from '@uiw/react-md-editor/commands';
import type { ICommand } from '@uiw/react-md-editor/commands';
import '@uiw/react-md-editor/markdown-editor.css';
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import {
  PiColumns,
  PiCopySimple,
  PiEye,
  PiFilePlus,
  PiFileText,
  PiFloppyDisk,
  PiFolderOpen,
  PiFolders,
  PiImage,
  PiMagicWand,
  PiPencilSimple,
  PiTable,
  PiTrash,
  PiUploadSimple,
} from 'react-icons/pi';
import { Markdown } from '@/components/Markdown';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { LayoutBody } from '@/layout/LayoutBody';
import { baseName, fileToBase64, formatBytes, triggerDownload } from './format';
import type { EditorConversion, EditorExportOptions, EditorFile, EditorFileKind } from './types';
import {
  fetchConversion,
  fetchFileContent,
  useEditorActions,
  useEditorConfig,
  useEditorProject,
  useEditorProjects,
} from './useProcuretechEditor';
import './procuretechEditor.css';

type TreeNode = {
  name: string;
  path: string;
  type: 'dir' | 'file';
  kind?: EditorFileKind;
  size?: number;
  children: TreeNode[];
};

const TEXT_KINDS: ReadonlySet<EditorFileKind> = new Set(['markdown', 'text']);

const buildTree = (files: EditorFile[]): TreeNode[] => {
  const root: TreeNode = { name: '', path: '', type: 'dir', children: [] };
  for (const f of files) {
    const segments = f.rel_path.split('/');
    let cursor = root;
    segments.forEach((seg, idx) => {
      const isLeaf = idx === segments.length - 1;
      // `.keep` は空フォルダ保持用センチネル。ファイルとしては表示しない。
      if (isLeaf && seg === '.keep') return;
      const path = segments.slice(0, idx + 1).join('/');
      let child = cursor.children.find((c) => c.name === seg);
      if (!child) {
        child = {
          name: seg,
          path,
          type: isLeaf ? 'file' : 'dir',
          kind: isLeaf ? f.kind : undefined,
          size: isLeaf ? f.size : undefined,
          children: [],
        };
        cursor.children.push(child);
      }
      cursor = child;
    });
  }
  const sort = (node: TreeNode) => {
    node.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name, 'ja');
    });
    node.children.forEach(sort);
  };
  sort(root);
  return root.children;
};

const FileIcon = ({ kind }: { kind?: EditorFileKind }) => {
  if (kind === 'excel') return <PiTable className='size-4 shrink-0 text-green-700' />;
  if (kind === 'image') return <PiImage className='size-4 shrink-0 text-purple-700' />;
  return <PiFileText className='size-4 shrink-0 text-solid-gray-600' />;
};

// ツールバーのカスタムコマンド（表挿入・AI校正プレースホルダ）。
const insertTable: ICommand = {
  name: 'insert-table',
  keyCommand: 'insert-table',
  buttonProps: { 'aria-label': '表を挿入', title: '表を挿入' },
  icon: <PiTable style={{ width: 16, height: 16 }} />,
  execute: (_state, api) => {
    api.replaceSelection('\n| 見出し1 | 見出し2 |\n| --- | --- |\n| 値1 | 値2 |\n');
  },
};

const aiProofread: ICommand = {
  name: 'ai-proofread',
  keyCommand: 'ai-proofread',
  buttonProps: { 'aria-label': 'AI校正（近日対応）', title: 'AI校正（近日対応）', disabled: true },
  icon: <PiMagicWand style={{ width: 16, height: 16 }} />,
  execute: () => {},
};

// 見出しは H1〜H6 を選べるドロップダウン（参考実装のプルダウン相当）。
const headingGroup: ICommand = commands.group(
  [
    commands.title1,
    commands.title2,
    commands.title3,
    commands.title4,
    commands.title5,
    commands.title6,
  ],
  {
    name: 'title',
    groupName: 'title',
    buttonProps: { 'aria-label': '見出し (H1〜H6)', title: '見出し (H1〜H6)' },
  },
);

const EDITOR_COMMANDS: ICommand[] = [
  headingGroup,
  commands.divider,
  commands.bold,
  commands.italic,
  commands.strikethrough,
  commands.hr,
  commands.divider,
  commands.link,
  commands.quote,
  commands.code,
  commands.codeBlock,
  commands.image,
  insertTable,
  commands.divider,
  commands.unorderedListCommand,
  commands.orderedListCommand,
  commands.checkedListCommand,
];

const EDITOR_EXTRA_COMMANDS: ICommand[] = [aiProofread];

type ViewMode = 'split' | 'edit' | 'preview';

const PROJECTS_TAB = 'projects';
const EDIT_TAB = 'edit';
const EXPORT_TAB = 'export';

const EXPORT_ITEMS: { key: keyof EditorExportOptions; label: string; def: boolean }[] = [
  { key: 'allow_specification', label: '調達仕様書', def: true },
  { key: 'allow_rfi', label: 'RFI（情報提供依頼）', def: true },
  { key: 'allow_quotation', label: '見積依頼', def: true },
  { key: 'allow_primaryexam', label: '一次審査資料', def: false },
];

const FileManagerModal = ({
  open,
  onClose,
  tree,
  selectedPath,
  busy,
  onOpen,
  onNew,
  onUpload,
  onRename,
  onDuplicate,
  onDelete,
}: {
  open: boolean;
  onClose: () => void;
  tree: TreeNode[];
  selectedPath: string | null;
  busy: boolean;
  onOpen: (path: string) => void;
  onNew: () => void;
  onUpload: (files: FileList | null) => void;
  onRename: (path: string) => void;
  onDuplicate: (path: string) => void;
  onDelete: (path: string) => void;
}) => {
  const uploadRef = useRef<HTMLInputElement>(null);

  const renderNodes = (nodes: TreeNode[], depth: number): ReactNode =>
    nodes.map((node) =>
      node.type === 'dir' ? (
        <li key={node.path}>
          <div
            className='flex items-center gap-1.5 py-1 text-dns-14N-130 text-solid-gray-700'
            style={{ paddingLeft: `${depth * 16}px` }}
          >
            <PiFolderOpen className='size-4 shrink-0 text-amber-600' />
            <span className='truncate'>{node.name}</span>
          </div>
          <ul>{renderNodes(node.children, depth + 1)}</ul>
        </li>
      ) : (
        <li key={node.path}>
          <div
            className={
              node.path === selectedPath
                ? 'flex items-center gap-2 rounded-4 bg-blue-50 px-2 py-1.5'
                : 'flex items-center gap-2 rounded-4 px-2 py-1.5 hover:bg-solid-gray-50'
            }
            style={{ paddingLeft: `${depth * 16 + 8}px` }}
          >
            <button
              type='button'
              onClick={() => onOpen(node.path)}
              className='flex min-w-0 flex-1 items-center gap-1.5 text-left'
            >
              <FileIcon kind={node.kind} />
              <span className='truncate text-std-14N-160 text-solid-gray-900'>{node.name}</span>
              {typeof node.size === 'number' && (
                <span className='shrink-0 text-dns-14N-130 text-solid-gray-500'>
                  {formatBytes(node.size)}
                </span>
              )}
            </button>
            <button
              type='button'
              disabled={busy}
              onClick={() => onRename(node.path)}
              title='リネーム'
              className='rounded-4 p-1 text-solid-gray-600 hover:bg-white disabled:opacity-50'
            >
              <PiPencilSimple className='size-4' />
            </button>
            <button
              type='button'
              disabled={busy}
              onClick={() => onDuplicate(node.path)}
              title='複製'
              className='rounded-4 p-1 text-solid-gray-600 hover:bg-white disabled:opacity-50'
            >
              <PiCopySimple className='size-4' />
            </button>
            <button
              type='button'
              disabled={busy}
              onClick={() => onDelete(node.path)}
              title='削除'
              className='rounded-4 p-1 text-error-1 hover:bg-white disabled:opacity-50'
            >
              <PiTrash className='size-4' />
            </button>
          </div>
        </li>
      ),
    );

  return (
    <CustomDialog isOpen={open} onClose={onClose}>
      <CustomDialogPanel className='max-w-xl'>
        <CustomDialogHeader hasClose onClose={onClose}>
          <span className='inline-flex items-center gap-2'>
            <PiFolders className='size-6 text-solid-gray-700' />
            フォルダ・ファイル管理
          </span>
        </CustomDialogHeader>
        <CustomDialogBody>
          <div className='mb-3 flex flex-wrap items-center gap-2'>
            <Button type='button' variant='outline' size='sm' disabled={busy} onClick={onNew}>
              <span className='inline-flex items-center gap-1'>
                <PiFilePlus className='size-4' />
                新規 Markdown
              </span>
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={busy}
              onClick={() => uploadRef.current?.click()}
            >
              <span className='inline-flex items-center gap-1'>
                <PiUploadSimple className='size-4' />
                アップロード
              </span>
            </Button>
            <input
              ref={uploadRef}
              type='file'
              multiple
              className='sr-only'
              onChange={(e) => {
                onUpload(e.target.files);
                if (uploadRef.current) uploadRef.current.value = '';
              }}
            />
          </div>
          <div className='max-h-[60vh] overflow-auto rounded-8 border border-solid-gray-300 p-2'>
            {tree.length === 0 ? (
              <p className='px-2 py-6 text-center text-dns-14N-130 text-solid-gray-500'>
                ファイルがありません。「新規 Markdown」またはアップロードで追加してください。
              </p>
            ) : (
              <ul className='flex flex-col'>{renderNodes(tree, 0)}</ul>
            )}
          </div>
          <p className='mt-3 text-dns-14N-130 text-solid-gray-600'>
            ファイル名をクリックするとエディタで開きます。リネーム・複製・削除はここで行います。
          </p>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};

export const ProcuretechEditorPage = () => {
  const { config, unavailable } = useEditorConfig();
  const {
    projects,
    loadError: projectsError,
    mutate: mutateProjects,
  } = useEditorProjects();
  const [projectId, setProjectId] = useState<string | null>(null);
  const {
    project,
    files,
    loadError: projectError,
    mutate: mutateProject,
  } = useEditorProject(projectId);
  const actions = useEditorActions();

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [baseline, setBaseline] = useState('');
  const [binaryUrl, setBinaryUrl] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);

  const [activeTab, setActiveTab] = useState<string>(PROJECTS_TAB);
  const [viewMode, setViewMode] = useState<ViewMode>('split');
  const [savedNotice, setSavedNotice] = useState(false);
  const [fileModalOpen, setFileModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [pageError, setPageError] = useState<string | null>(null);

  // 書き出し（変換）の進行状態。
  const [exportOptions, setExportOptions] = useState<EditorExportOptions>(
    Object.fromEntries(EXPORT_ITEMS.map((i) => [i.key, i.def])) as EditorExportOptions,
  );
  const [conversion, setConversion] = useState<
    | { phase: 'idle' }
    | { phase: 'running'; requestId: string; status?: string }
    | { phase: 'done'; url?: string; filename?: string }
    | { phase: 'error'; message: string }
  >({ phase: 'idle' });

  const tree = useMemo(() => buildTree(files), [files]);
  const selected = useMemo(
    () => files.find((f) => f.rel_path === selectedPath) ?? null,
    [files, selectedPath],
  );
  const isEditable = selected ? TEXT_KINDS.has(selected.kind) : false;
  const isMarkdown = selected?.kind === 'markdown';
  const isDirty = isEditable && draft !== baseline;
  const storageOk = config?.storage_configured !== false;

  // 編集ペインとプレビューペインのスクロール連動（Markdown の分割表示時のみ）。
  const editorWrapRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (viewMode !== 'split' || !isMarkdown) return;
    const wrap = editorWrapRef.current;
    const preview = previewRef.current;
    if (!wrap || !preview) return;
    const scroller =
      wrap.querySelector<HTMLElement>('.w-md-editor-area') ??
      wrap.querySelector<HTMLElement>('.w-md-editor-content');
    if (!scroller) return;

    let lock: 'editor' | 'preview' | null = null;
    const ratioOf = (el: HTMLElement) =>
      el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight);
    const onEditorScroll = () => {
      if (lock === 'preview') {
        lock = null;
        return;
      }
      lock = 'editor';
      preview.scrollTop = ratioOf(scroller) * (preview.scrollHeight - preview.clientHeight);
    };
    const onPreviewScroll = () => {
      if (lock === 'editor') {
        lock = null;
        return;
      }
      lock = 'preview';
      scroller.scrollTop = ratioOf(preview) * (scroller.scrollHeight - scroller.clientHeight);
    };
    scroller.addEventListener('scroll', onEditorScroll);
    preview.addEventListener('scroll', onPreviewScroll);
    return () => {
      scroller.removeEventListener('scroll', onEditorScroll);
      preview.removeEventListener('scroll', onPreviewScroll);
    };
  }, [viewMode, isMarkdown]);

  // 変換ステータスのポーリング。
  useEffect(() => {
    if (conversion.phase !== 'running' || !projectId) return;
    let stop = false;
    const timer = window.setInterval(async () => {
      if (stop) return;
      try {
        const res: EditorConversion = await fetchConversion(conversion.requestId, projectId);
        const status = String(res.status ?? '').toLowerCase();
        if (status === 'success' || res.download_url) {
          setConversion({
            phase: 'done',
            url: res.download_url,
            filename: res.download_filename,
          });
        } else if (status === 'error' || status === 'failed' || res.error) {
          setConversion({
            phase: 'error',
            message: res.error || res.download_error || '変換に失敗しました。',
          });
        } else {
          setConversion({ phase: 'running', requestId: conversion.requestId, status });
        }
      } catch (_e) {
        setConversion({ phase: 'error', message: '変換状況の取得に失敗しました。' });
      }
    }, 2500);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [conversion, projectId]);

  // プロジェクト選択タブへ戻った際は一覧を再検証する。
  // （ファイル追加/複製/削除は単一プロジェクトしか mutate しないため、
  //  一覧側の file_count が古いまま 0 表示になるのを防ぐ。）
  useEffect(() => {
    if (activeTab === PROJECTS_TAB) mutateProjects();
  }, [activeTab, mutateProjects]);

  const openProject = (id: string) => {
    setProjectId(id);
    setSelectedPath(null);
    setDraft('');
    setBaseline('');
    setBinaryUrl(null);
    setActiveTab(EDIT_TAB);
    setSavedNotice(false);
    setConversion({ phase: 'idle' });
    setPageError(null);
  };

  const openFile = async (path: string) => {
    setFileModalOpen(false);
    setSelectedPath(path);
    setSavedNotice(false);
    setBinaryUrl(null);
    const f = files.find((x) => x.rel_path === path);
    if (!f || !projectId) return;
    setFileLoading(true);
    try {
      const content = await fetchFileContent(projectId, path);
      if (TEXT_KINDS.has(f.kind)) {
        setDraft(content.content ?? '');
        setBaseline(content.content ?? '');
      } else {
        setDraft('');
        setBaseline('');
        setBinaryUrl(content.download_url ?? null);
      }
    } catch (_e) {
      setPageError('ファイルの読み込みに失敗しました。');
    } finally {
      setFileLoading(false);
    }
  };

  const onSave = async () => {
    if (!selected || !projectId || !isEditable) return;
    const res = await actions.saveFile(projectId, selected.rel_path, draft);
    if (res) {
      setBaseline(draft);
      setSavedNotice(true);
      window.setTimeout(() => setSavedNotice(false), 2000);
      mutateProject();
    }
  };

  const onCreateProject = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    const created = await actions.createProject(name);
    if (created) {
      setNewProjectName('');
      mutateProjects();
      openProject(created.id);
    }
  };

  const onDeleteProject = async (id: string, name: string) => {
    if (!window.confirm(`プロジェクト「${name}」を削除しますか？（フォルダ内のファイルも削除されます）`)) {
      return;
    }
    const ok = await actions.deleteProject(id);
    if (ok) {
      if (projectId === id) {
        setProjectId(null);
        setActiveTab(PROJECTS_TAB);
      }
      mutateProjects();
    }
  };

  const onNewFile = async () => {
    if (!projectId) return;
    const name = window.prompt(
      '新規 Markdown ファイル名（フォルダは 図/メモ.md のように指定可）',
      '新規ドキュメント.md',
    );
    if (!name) return;
    const path = name.endsWith('.md') ? name : `${name}.md`;
    if (files.some((f) => f.rel_path === path)) {
      window.alert('同名のファイルが既に存在します。');
      return;
    }
    const res = await actions.saveFile(projectId, path, `# ${baseName(path).replace(/\.md$/, '')}\n\n`);
    if (res) {
      await mutateProject();
      mutateProjects();
      openFile(path);
    }
  };

  const onUpload = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0 || !projectId) return;
    for (const file of Array.from(fileList)) {
      const content_b64 = await fileToBase64(file);
      await actions.uploadFile(projectId, { filename: file.name, content_b64 });
    }
    mutateProject();
    mutateProjects();
  };

  const onRenamePath = async (path: string) => {
    if (!projectId) return;
    const next = window.prompt('新しいパス名', path);
    if (!next || next === path) return;
    if (files.some((f) => f.rel_path === next)) {
      window.alert('同名のファイルが既に存在します。');
      return;
    }
    const res = await actions.renameFile(projectId, path, next);
    if (res) {
      if (selectedPath === path) setSelectedPath(next);
      mutateProject();
    }
  };

  const onDuplicatePath = async (path: string) => {
    if (!projectId) return;
    const res = await actions.duplicateFile(projectId, path);
    if (res) {
      mutateProject();
      mutateProjects();
    }
  };

  const onDeletePath = async (path: string) => {
    if (!projectId) return;
    if (!window.confirm(`「${path}」を削除しますか？`)) return;
    const ok = await actions.deleteFile(projectId, path);
    if (ok) {
      if (selectedPath === path) {
        setSelectedPath(null);
        setDraft('');
        setBaseline('');
      }
      mutateProject();
      mutateProjects();
    }
  };

  const onExport = async () => {
    if (!projectId) return;
    setConversion({ phase: 'idle' });
    const res = await actions.exportProject(projectId, exportOptions);
    if (!res) return;
    const status = String(res.status ?? '').toLowerCase();
    if (res.download_url || status === 'success') {
      setConversion({ phase: 'done', url: res.download_url, filename: res.download_filename });
    } else if (res.request_id) {
      setConversion({ phase: 'running', requestId: res.request_id, status });
    } else if (res.error) {
      setConversion({ phase: 'error', message: res.error });
    } else {
      setConversion({ phase: 'error', message: '変換を開始できませんでした。' });
    }
  };

  const viewBtn = (mode: ViewMode, label: string, icon: ReactNode) => (
    <button
      type='button'
      onClick={() => setViewMode(mode)}
      className={
        mode === viewMode
          ? 'flex items-center gap-1 rounded-4 bg-blue-900 px-2.5 py-1.5 text-dns-14N-130 text-white'
          : 'flex items-center gap-1 rounded-4 px-2.5 py-1.5 text-dns-14N-130 text-solid-gray-700 hover:bg-solid-gray-50'
      }
      aria-pressed={mode === viewMode}
    >
      {icon}
      {label}
    </button>
  );

  const tabBtn = (key: string, label: string) => (
    <button
      key={key}
      type='button'
      onClick={() => setActiveTab(key)}
      className={
        key === activeTab
          ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
          : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900'
      }
    >
      {label}
    </button>
  );

  return (
    <LayoutBody>
      <PageTitle title='情報化企画書エディタ' />

      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'>
        <div className='flex flex-col gap-1'>
          <h1 className='text-std-22B-150 text-solid-gray-900'>情報化企画書エディタ</h1>
          <p className='text-dns-16N-170 text-solid-gray-700'>
            案件フォルダ内の生成文書（Markdown）を編集・校正し、Word 文書へ統合する準備を行います。
          </p>
        </div>

        {unavailable && (
          <div
            className='rounded-8 border border-amber-300 bg-amber-50 px-4 py-2 text-dns-14N-130 text-solid-gray-800'
            role='status'
          >
            情報化企画書エディタは現在利用できません（サービス未起動）。
            {config?.error ? ` ${config.error}` : ''}
          </div>
        )}
        {!unavailable && !storageOk && (
          <div
            className='rounded-8 border border-amber-300 bg-amber-50 px-4 py-2 text-dns-14N-130 text-solid-gray-800'
            role='status'
          >
            ストレージ（S3 互換）が未設定のため、保存・アップロードに失敗する可能性があります。
          </div>
        )}
        {(pageError || projectsError || projectError || actions.error) && (
          <div
            className='rounded-8 border border-error-2 bg-error-3 px-4 py-2 text-dns-14N-130 text-error-1'
            role='alert'
          >
            {pageError || projectsError || projectError || actions.error}
          </div>
        )}

        <div className='flex flex-wrap gap-1 overflow-x-auto border-b border-solid-gray-300'>
          {tabBtn(PROJECTS_TAB, 'プロジェクト選択')}
          {tabBtn(EDIT_TAB, '編集')}
          {tabBtn(EXPORT_TAB, '書き出し・統合')}
        </div>

        {activeTab === PROJECTS_TAB && (
          <section className='flex flex-col gap-3'>
            <div className='flex flex-wrap items-end justify-between gap-2'>
              <h2 className='text-std-18B-160 text-solid-gray-900'>案件フォルダ一覧</h2>
              <div className='flex items-end gap-2'>
                <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                  新規プロジェクト名
                  <input
                    type='text'
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    placeholder='20250902_調達管理システム更新'
                    className='w-64 rounded-8 border border-solid-gray-300 px-3 py-1.5 text-std-16N-170'
                  />
                </label>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  disabled={actions.submitting || !newProjectName.trim()}
                  onClick={onCreateProject}
                >
                  <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                    <PiFilePlus className='size-4' />
                    作成
                  </span>
                </Button>
              </div>
            </div>
            <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
              <table className='w-full min-w-[560px] border-collapse text-dns-14N-130'>
                <thead>
                  <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                    <th className='px-3 py-2'>プロジェクト名</th>
                    <th className='px-3 py-2'>作成日時</th>
                    <th className='px-3 py-2'>ファイル数</th>
                    <th className='px-3 py-2 text-right'>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.length === 0 ? (
                    <tr>
                      <td colSpan={4} className='px-3 py-6 text-center text-solid-gray-500'>
                        プロジェクトがありません。右上から新規作成してください。
                      </td>
                    </tr>
                  ) : (
                    projects.map((p) => (
                      <tr key={p.id} className='border-b border-solid-gray-200 last:border-b-0'>
                        <td className='px-3 py-2'>
                          <button
                            type='button'
                            onClick={() => openProject(p.id)}
                            className='text-left text-std-16N-170 text-blue-900 underline-offset-2 hover:underline'
                          >
                            {p.name}
                          </button>
                          {p.id === projectId && (
                            <span className='ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                              選択中
                            </span>
                          )}
                        </td>
                        <td className='px-3 py-2 text-solid-gray-600'>
                          {new Date(p.created_at).toLocaleString('ja-JP')}
                        </td>
                        <td className='px-3 py-2 text-solid-gray-700'>{p.file_count}</td>
                        <td className='px-3 py-2 text-right'>
                          <span className='inline-flex gap-2'>
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              onClick={() => openProject(p.id)}
                            >
                              開く
                            </Button>
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              disabled={actions.submitting}
                              onClick={() => onDeleteProject(p.id, p.name)}
                            >
                              削除
                            </Button>
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {activeTab === EDIT_TAB && !project && (
          <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
            「プロジェクト選択」タブから案件フォルダを開いてください。
          </div>
        )}

        {activeTab === EDIT_TAB && project && (
          <>
            <div className='flex flex-wrap items-center gap-2 rounded-8 border border-solid-gray-300 px-3 py-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                onClick={() => setFileModalOpen(true)}
              >
                <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                  <PiFolders className='size-4' />
                  ファイル管理
                </span>
              </Button>

              <span className='flex flex-wrap items-center gap-1.5 text-std-14N-160'>
                <PiFolders className='size-4 shrink-0 text-solid-gray-500' />
                <span className='font-medium text-solid-gray-800'>{project.name}</span>
                <span className='text-solid-gray-400'>/</span>
                <PiFileText className='size-4 shrink-0 text-solid-gray-500' />
                <span className='text-std-16B-150 text-solid-gray-900'>
                  {selected ? selected.rel_path : '（ファイル未選択）'}
                </span>
                {isDirty && (
                  <span className='rounded-full bg-amber-100 px-2 py-0.5 text-dns-14N-130 text-amber-800'>
                    未保存
                  </span>
                )}
                {savedNotice && (
                  <span className='rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                    保存しました
                  </span>
                )}
              </span>

              <span className='ml-auto flex items-center gap-2'>
                {isMarkdown && (
                  <div className='flex items-center gap-0.5 rounded-4 border border-solid-gray-300 p-0.5'>
                    {viewBtn('split', '分割', <PiColumns className='size-4' />)}
                    {viewBtn('edit', '編集', <PiPencilSimple className='size-4' />)}
                    {viewBtn('preview', 'プレビュー', <PiEye className='size-4' />)}
                  </div>
                )}
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  disabled={!isEditable || !isDirty || actions.submitting}
                  onClick={onSave}
                >
                  <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                    <PiFloppyDisk className='size-4' />
                    保存
                  </span>
                </Button>
              </span>
            </div>

            {fileLoading && (
              <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
                読み込み中…
              </div>
            )}

            {!fileLoading && selected == null && (
              <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
                「ファイル管理」から編集するファイルを選択してください。
              </div>
            )}

            {!fileLoading && selected != null && !isEditable && (
              <div className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
                <p>
                  {selected.kind === 'excel'
                    ? 'Excel ファイル（情報化企画書 / 全般的事項）はエディタでは編集しません。'
                    : 'このファイル形式はエディタでの編集に対応していません。'}
                </p>
                {binaryUrl && (
                  <div>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      onClick={() => triggerDownload(binaryUrl, baseName(selected.rel_path))}
                    >
                      ダウンロード
                    </Button>
                  </div>
                )}
              </div>
            )}

            {!fileLoading && selected != null && isEditable && (
              <div
                data-color-mode='light'
                className='grid h-[calc(100dvh-260px)] min-h-[520px] gap-3'
                style={{
                  gridTemplateColumns:
                    isMarkdown && viewMode === 'split'
                      ? 'minmax(0,1fr) minmax(0,1fr)'
                      : 'minmax(0,1fr)',
                }}
              >
                {(!isMarkdown || viewMode !== 'preview') && (
                  <div
                    ref={editorWrapRef}
                    className='pte-md h-full overflow-hidden rounded-8 border border-solid-gray-300'
                  >
                    <MDEditor
                      value={draft}
                      onChange={(v) => setDraft(v ?? '')}
                      preview='edit'
                      height='100%'
                      visibleDragbar={false}
                      commands={EDITOR_COMMANDS}
                      extraCommands={EDITOR_EXTRA_COMMANDS}
                    />
                  </div>
                )}
                {isMarkdown && viewMode !== 'edit' && (
                  <div
                    ref={previewRef}
                    className='h-full overflow-auto rounded-8 border border-solid-gray-300 bg-white p-4'
                  >
                    <Markdown>{draft || '（本文がありません）'}</Markdown>
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {activeTab === EXPORT_TAB && !project && (
          <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
            「プロジェクト選択」タブから案件フォルダを開いてください。
          </div>
        )}

        {activeTab === EXPORT_TAB && project && (
          <section className='flex flex-col gap-4'>
            <div className='rounded-8 border border-solid-gray-300 p-4'>
              <h2 className='text-std-18B-160 text-solid-gray-900'>Word 文書へ統合</h2>
              <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                案件フォルダ内の Markdown を Word 文書へ統合します（外部 Word 変換 API を利用）。
              </p>
              {config?.convert_configured === false && (
                <p className='mt-2 rounded-8 border border-amber-300 bg-amber-50 px-3 py-2 text-dns-14N-130 text-solid-gray-800'>
                  Word 変換 API が未設定です（EDITOR_CONVERT_URL）。管理者に設定を依頼してください。
                </p>
              )}
              <div className='mt-3 flex flex-col gap-2'>
                {EXPORT_ITEMS.map((item) => (
                  <label key={item.key} className='flex items-center gap-2 text-std-16N-170'>
                    <input
                      type='checkbox'
                      checked={Boolean(exportOptions[item.key])}
                      onChange={(e) =>
                        setExportOptions((prev) => ({ ...prev, [item.key]: e.target.checked }))
                      }
                      className='size-4'
                    />
                    {item.label}
                  </label>
                ))}
              </div>
              <div className='mt-4 flex items-center gap-3'>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='md'
                  disabled={
                    config?.convert_configured === false ||
                    actions.submitting ||
                    conversion.phase === 'running'
                  }
                  onClick={onExport}
                >
                  統合して変換
                </Button>
                {conversion.phase === 'running' && (
                  <span className='text-dns-14N-130 text-solid-gray-600'>
                    変換中…{conversion.status ? `（${conversion.status}）` : ''}
                  </span>
                )}
                {conversion.phase === 'error' && (
                  <span className='text-dns-14N-130 text-error-1'>{conversion.message}</span>
                )}
              </div>
              {conversion.phase === 'done' && (
                <div className='mt-4 rounded-8 border border-blue-300 bg-blue-50 px-3 py-3 text-std-16N-170 text-solid-gray-800'>
                  変換が完了しました。
                  {conversion.url ? (
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      className='ml-3'
                      onClick={() => triggerDownload(conversion.url as string, conversion.filename)}
                    >
                      ダウンロード
                    </Button>
                  ) : (
                    <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>
                      変換結果は連携先（Nextcloud 等）に出力されました。
                    </span>
                  )}
                </div>
              )}
            </div>
          </section>
        )}
      </div>

      <FileManagerModal
        open={fileModalOpen}
        onClose={() => setFileModalOpen(false)}
        tree={tree}
        selectedPath={selectedPath}
        busy={actions.submitting}
        onOpen={openFile}
        onNew={onNewFile}
        onUpload={onUpload}
        onRename={onRenamePath}
        onDuplicate={onDuplicatePath}
        onDelete={onDeletePath}
      />
    </LayoutBody>
  );
};
