import MDEditor from '@uiw/react-md-editor';
import type { ICommand, TextAreaTextApi } from '@uiw/react-md-editor/commands';
import * as commands from '@uiw/react-md-editor/commands';
import '@uiw/react-md-editor/markdown-editor.css';
import type { PredictRequest } from 'genai-web';
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  PiArrowDown,
  PiArrowUp,
  PiColumns,
  PiCopySimple,
  PiDownloadSimple,
  PiEye,
  PiFilePlus,
  PiFileText,
  PiFloppyDisk,
  PiFolderOpen,
  PiFolders,
  PiImage,
  PiMagicWand,
  PiPencilSimple,
  PiPlus,
  PiTable,
  PiTrash,
  PiTreeStructure,
  PiUploadSimple,
} from 'react-icons/pi';
import { Markdown } from '@/components/Markdown';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { mermaidToPngDataUrl } from '@/features/exapp/utils/mermaid';
import { MERMAID_DIAGRAM_TYPES } from '@/features/generate-diagram/constants';
import type { MermaidDiagramType } from '@/features/generate-diagram/types';
import { extractDiagramCode } from '@/features/generate-diagram/utils/extractDiagram';
import { LayoutBody } from '@/layout/LayoutBody';
import { predict } from '@/lib/chatApi';
import { findModelByModelId, resolveSelectedModelId } from '@/models';
import { getPrompter } from '@/prompts';
import {
  baseName,
  extractImageSources,
  fileToBase64,
  formatBytes,
  rewriteImageSources,
  triggerDownload,
} from './format';
import type {
  EditorComposition,
  EditorCompositionItem,
  EditorCompositionOutput,
  EditorFile,
  EditorFileKind,
  EditorGenerateTheme,
} from './types';
import {
  fetchFileContent,
  fetchGeneration,
  useEditorActions,
  useEditorComposition,
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

const EDITOR_EXTRA_COMMANDS: ICommand[] = [aiProofread];

// AI 図生成で選べるタイプ（AI 自動 + Mermaid 各種）。
const DIAGRAM_TYPE_OPTIONS: { value: 'AI' | MermaidDiagramType; label: string }[] = [
  { value: 'AI', label: 'AI におまかせ（自動判定）' },
  ...(Object.entries(MERMAID_DIAGRAM_TYPES) as [MermaidDiagramType, string][]).map(
    ([value, label]) => ({ value, label }),
  ),
];

type ViewMode = 'split' | 'edit' | 'preview';

// プレビューの見出し・表スタイル（プレビュー表示専用。保存内容には影響しない）。
// spec-app の Word 出力（custom-reference.docx）の見た目に寄せた「調達仕様書風」を含む。
type PreviewStyle = 'plain' | 'spec' | 'numbered';
const PREVIEW_STYLE_OPTIONS: { value: PreviewStyle; label: string }[] = [
  { value: 'plain', label: 'プレーン' },
  { value: 'spec', label: '調達仕様書風（第N章）' },
  { value: 'numbered', label: '番号付き（1 / 1.1）' },
];
const PREVIEW_STYLE_STORAGE_KEY = 'procuretech-editor:previewStyle';
const previewStyleClass = (style: PreviewStyle): string =>
  style === 'spec'
    ? 'pte-preview pte-preview--spec'
    : style === 'numbered'
      ? 'pte-preview pte-preview--numbered'
      : '';

const PROJECTS_TAB = 'projects';
const EDIT_TAB = 'edit';
const EXPORT_TAB = 'export';

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

// 出力ファイルの合成定義エディタ（書き出し・統合タブ）。
// テーマ既定を初期表示し、プロジェクト単位で並べ替え・ON/OFF・出力追加を上書きできる。
const CompositionEditor = ({ projectId }: { projectId: string }) => {
  const { data, isLoading, mutate } = useEditorComposition(projectId);
  const actions = useEditorActions();
  const [outputs, setOutputs] = useState<EditorCompositionOutput[]>([]);
  const [dirty, setDirty] = useState(false);
  const [newOutputName, setNewOutputName] = useState('');
  const [savedNotice, setSavedNotice] = useState(false);
  const [compose, setCompose] = useState<
    | { phase: 'idle' }
    | { phase: 'running' }
    | {
        phase: 'done';
        url?: string;
        filename?: string;
        names?: string[];
        skipped?: { name: string; reason: string }[];
      }
    | { phase: 'error'; message: string }
  >({ phase: 'idle' });

  // サーバから取得した定義でローカル状態を初期化（プロジェクト/取得結果が変わったとき）。
  const loadedKey = data ? `${projectId}:${data.saved}:${data.composition.outputs.length}` : null;
  const initRef = useRef<string | null>(null);
  useEffect(() => {
    if (!data || !loadedKey) return;
    if (initRef.current === loadedKey) return;
    initRef.current = loadedKey;
    setOutputs(data.composition.outputs.map((o) => ({ ...o, items: [...o.items] })));
    setDirty(false);
  }, [data, loadedKey]);

  const theme = data?.theme;
  const files = useMemo(() => data?.files ?? [], [data]);
  const sectionLabel = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of theme?.sections ?? []) m[s.key] = s.label;
    return m;
  }, [theme]);
  const fileByKey = useMemo(() => {
    const m: Record<string, (typeof files)[number]> = {};
    for (const f of files) if (f.section_key) m[f.section_key] ??= f;
    return m;
  }, [files]);
  const fileById = useMemo(() => {
    const m: Record<string, (typeof files)[number]> = {};
    for (const f of files) m[f.id] = f;
    return m;
  }, [files]);

  // ある合成項目の表示情報（ラベル・実ファイル有無）を解決する。
  const resolveItem = useCallback(
    (item: EditorCompositionItem) => {
      if (item.section_key) {
        const f = fileByKey[item.section_key];
        return {
          label: sectionLabel[item.section_key] ?? item.section_key,
          path: f?.rel_path,
          available: !!f,
        };
      }
      if (item.file_id) {
        const f = fileById[item.file_id];
        return { label: f?.rel_path ?? '(不明なファイル)', path: f?.rel_path, available: !!f };
      }
      return { label: '(不明)', path: undefined, available: false };
    },
    [fileByKey, fileById, sectionLabel],
  );

  // Excel 出力に紐づく section key（Markdown の「章を追加」候補からは除外する）。
  const excelSectionKeys = useMemo(() => {
    const s = new Set<string>();
    for (const o of theme?.outputs ?? []) {
      if (o.kind === 'excel') for (const k of o.sections) s.add(k);
    }
    return s;
  }, [theme]);

  // 追加候補（章＝生成 section / その他＝手動の md・text ファイル）。
  const composable = useMemo(
    () => files.filter((f) => f.kind === 'markdown' || f.kind === 'text'),
    [files],
  );
  const sectionOptions = useMemo(
    () => (theme?.sections ?? []).filter((s) => !!fileByKey[s.key] && !excelSectionKeys.has(s.key)),
    [theme, fileByKey, excelSectionKeys],
  );
  const fileOptions = useMemo(() => composable.filter((f) => !f.section_key), [composable]);

  const update = useCallback((next: EditorCompositionOutput[]) => {
    setOutputs(next);
    setDirty(true);
  }, []);

  const patchOutput = useCallback(
    (idx: number, patch: Partial<EditorCompositionOutput>) => {
      update(outputs.map((o, i) => (i === idx ? { ...o, ...patch } : o)));
    },
    [outputs, update],
  );

  const moveItem = useCallback(
    (oi: number, ii: number, dir: -1 | 1) => {
      const items = [...outputs[oi].items];
      const j = ii + dir;
      if (j < 0 || j >= items.length) return;
      [items[ii], items[j]] = [items[j], items[ii]];
      patchOutput(oi, { items });
    },
    [outputs, patchOutput],
  );

  const removeItem = useCallback(
    (oi: number, ii: number) => {
      patchOutput(oi, { items: outputs[oi].items.filter((_, i) => i !== ii) });
    },
    [outputs, patchOutput],
  );

  const addItem = useCallback(
    (oi: number, value: string) => {
      if (!value) return;
      const [kind, key] = value.split(':', 2);
      const item: EditorCompositionItem = kind === 'sec' ? { section_key: key } : { file_id: key };
      patchOutput(oi, { items: [...outputs[oi].items, item] });
    },
    [outputs, patchOutput],
  );

  const addOutput = useCallback(() => {
    const name = newOutputName.trim();
    if (!name) return;
    update([...outputs, { id: `output-${Date.now()}`, name, enabled: true, items: [] }]);
    setNewOutputName('');
  }, [newOutputName, outputs, update]);

  const removeOutput = useCallback(
    (oi: number) => update(outputs.filter((_, i) => i !== oi)),
    [outputs, update],
  );

  const currentComposition = useCallback(
    (): EditorComposition => ({ theme: data?.composition.theme ?? theme?.id ?? '', outputs }),
    [data, theme, outputs],
  );

  const onSave = useCallback(async () => {
    const res = await actions.saveComposition(projectId, currentComposition());
    if (res) {
      setDirty(false);
      setSavedNotice(true);
      window.setTimeout(() => setSavedNotice(false), 2000);
      await mutate();
    }
  }, [actions, projectId, currentComposition, mutate]);

  // 合成に含まれる Markdown ファイルのうち、``` mermaid ブロックを持つものを
  // クライアント側で PNG 画像化し、画像参照へ差し替えた本文（overrides）を作る。
  // pandoc は Mermaid をそのままでは図にできないため、画像にして埋め込む。
  const materializeMermaid = useCallback(async (): Promise<Record<string, string>> => {
    const overrides: Record<string, string> = {};
    // 有効な Markdown 出力が参照するファイル（重複なし）を集める。
    const targets = new Map<string, string>(); // file id -> rel_path
    for (const o of outputs) {
      if (o.enabled === false || o.kind === 'excel') continue;
      for (const it of o.items) {
        const f = it.section_key
          ? fileByKey[it.section_key]
          : it.file_id
            ? fileById[it.file_id]
            : undefined;
        if (f && f.kind === 'markdown') targets.set(f.id, f.rel_path);
      }
    }
    const fence = /```mermaid[^\n]*\n([\s\S]*?)```/g;
    for (const [fileId, relPath] of targets) {
      const content = (await fetchFileContent(projectId, relPath))?.content ?? '';
      if (!/```mermaid/.test(content)) continue;
      const blocks: string[] = [];
      let m: RegExpExecArray | null;
      fence.lastIndex = 0;
      // biome-ignore lint/suspicious/noAssignInExpressions: 正規表現の逐次マッチ
      while ((m = fence.exec(content)) !== null) blocks.push(m[1]);
      if (blocks.length === 0) continue;

      // ブロックを順に画像化してアップロードし、参照 rel_path を得る。
      const replacements: string[] = [];
      for (let i = 0; i < blocks.length; i++) {
        try {
          const dataUrl = await mermaidToPngDataUrl(blocks[i]);
          const filename = `mermaid-${fileId}-${i}.png`;
          const uploaded = await actions.uploadFile(projectId, {
            filename,
            content_b64: dataUrl,
            dir: 'images',
          });
          replacements.push(uploaded ? `![diagram](${uploaded.rel_path})` : '');
        } catch {
          replacements.push(''); // 失敗時はそのブロックを空に（元コードは残さない）
        }
      }
      let idx = 0;
      fence.lastIndex = 0;
      const rewritten = content.replace(fence, (whole) => {
        const rep = replacements[idx++];
        return rep || whole; // 画像化に失敗した場合は元のブロックを残す
      });
      overrides[fileId] = rewritten;
    }
    return overrides;
  }, [outputs, fileByKey, fileById, projectId, actions]);

  const onCompose = useCallback(async () => {
    setCompose({ phase: 'running' });
    let overrides: Record<string, string> = {};
    try {
      overrides = await materializeMermaid();
    } catch {
      // 画像化に失敗しても合成自体は続行（Mermaid はコードのまま出力される）。
      overrides = {};
    }
    if (Object.keys(overrides).length > 0) {
      await mutate(); // 追加した画像ファイルを一覧へ反映
    }
    const res = await actions.composeProject(projectId, currentComposition(), overrides);
    if (res?.download_url) {
      setCompose({
        phase: 'done',
        url: res.download_url,
        filename: res.download_filename,
        names: res.outputs,
        skipped: res.skipped,
      });
    } else if (res?.error) {
      setCompose({ phase: 'error', message: res.error });
    } else if (actions.error) {
      setCompose({ phase: 'error', message: actions.error });
    } else {
      setCompose({ phase: 'error', message: 'Word 合成に失敗しました。' });
    }
  }, [actions, projectId, currentComposition, materializeMermaid, mutate]);

  if (isLoading && !data) {
    return (
      <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
        合成定義を読み込んでいます…
      </div>
    );
  }
  if (data?.error) {
    return (
      <div className='rounded-8 border border-amber-300 bg-amber-50 p-4 text-dns-14N-130 text-solid-gray-800'>
        {data.error}
      </div>
    );
  }

  const composeConfigured = theme?.configured !== false;
  const enabledCount = outputs.filter((o) => o.enabled).length;

  return (
    <section className='flex flex-col gap-4'>
      <div className='rounded-8 border border-solid-gray-300 p-4'>
        <h2 className='text-std-18B-160 text-solid-gray-900'>文書の書き出し・合成</h2>
        <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
          出力ファイルごとに含める章（Markdown）と順番を指定して Word へ合成します。見積総括表・
          一次審査表は生成時に作られる Excel をそのまま同梱します。
          {theme ? `（テーマ: ${theme.label}）` : ''}
        </p>
        {!composeConfigured && (
          <p className='mt-2 rounded-8 border border-amber-300 bg-amber-50 px-3 py-2 text-dns-14N-130 text-solid-gray-800'>
            このテーマの Word 合成 API が未設定です。管理者に設定を依頼してください。
          </p>
        )}

        <div className='mt-4 flex flex-col gap-4'>
          {outputs.map((out, oi) => {
            // Excel 出力（見積総括表・一次審査表）は「生成された単一ファイル」を出力するだけ。
            // 章の並べ替え UI は出さず、生成状況のみ表示する。
            if (out.kind === 'excel') {
              return (
                <div key={out.id} className='rounded-8 border border-solid-gray-300'>
                  <div className='flex items-center gap-2 border-b border-solid-gray-200 bg-solid-gray-50 px-3 py-2'>
                    <input
                      type='checkbox'
                      checked={out.enabled}
                      onChange={(e) => patchOutput(oi, { enabled: e.target.checked })}
                      className='size-4'
                      title='この出力ファイルを対象にする'
                    />
                    <input
                      type='text'
                      value={out.name}
                      onChange={(e) => patchOutput(oi, { name: e.target.value })}
                      className='min-w-0 flex-1 rounded-6 border border-solid-gray-300 px-2 py-1 text-std-16N-170'
                      placeholder='出力ファイル名'
                    />
                    <span className='shrink-0 text-dns-14N-130 text-solid-gray-500'>.xlsx</span>
                    <button
                      type='button'
                      onClick={() => removeOutput(oi)}
                      className='shrink-0 rounded-6 p-1 text-solid-gray-500 hover:bg-solid-gray-100 hover:text-error-1'
                      title='この出力ファイルを削除'
                    >
                      <PiTrash className='size-4' />
                    </button>
                  </div>
                  <div className='px-3 py-3 text-dns-14N-130 text-solid-gray-600'>
                    {out.builder === 'primaryexam' ? (
                      <span>
                        「書き出す」時に、その時点の各章（section2/4/5/6 相当）から
                        一次審査表を生成します。対象章が無い場合はスキップします。
                      </span>
                    ) : out.builder === 'quotation' ? (
                      <span>
                        「書き出す」時に、生成時の保存パラメータ（年度・フェーズ）から
                        見積総括表を生成します。
                      </span>
                    ) : (
                      <span>「書き出す」時に生成します。</span>
                    )}
                  </div>
                </div>
              );
            }
            return (
              <div key={out.id} className='rounded-8 border border-solid-gray-300'>
                <div className='flex items-center gap-2 border-b border-solid-gray-200 bg-solid-gray-50 px-3 py-2'>
                  <input
                    type='checkbox'
                    checked={out.enabled}
                    onChange={(e) => patchOutput(oi, { enabled: e.target.checked })}
                    className='size-4'
                    title='この出力ファイルを合成対象にする'
                  />
                  <input
                    type='text'
                    value={out.name}
                    onChange={(e) => patchOutput(oi, { name: e.target.value })}
                    className='min-w-0 flex-1 rounded-6 border border-solid-gray-300 px-2 py-1 text-std-16N-170'
                    placeholder='出力ファイル名'
                  />
                  <span className='shrink-0 text-dns-14N-130 text-solid-gray-500'>.docx</span>
                  <button
                    type='button'
                    onClick={() => removeOutput(oi)}
                    className='shrink-0 rounded-6 p-1 text-solid-gray-500 hover:bg-solid-gray-100 hover:text-error-1'
                    title='この出力ファイルを削除'
                  >
                    <PiTrash className='size-4' />
                  </button>
                </div>
                <div className='flex flex-col gap-1 p-3'>
                  {out.items.length === 0 && (
                    <p className='px-1 py-2 text-dns-14N-130 text-solid-gray-500'>
                      章が未設定です。下の「章を追加」から追加してください。
                    </p>
                  )}
                  {out.items.map((item, ii) => {
                    const info = resolveItem(item);
                    return (
                      <div
                        key={`${out.id}-${ii}-${item.section_key ?? item.file_id}`}
                        className='flex items-center gap-2 rounded-6 border border-solid-gray-200 px-2 py-1.5'
                      >
                        <span className='w-6 shrink-0 text-center text-dns-14N-130 text-solid-gray-400'>
                          {ii + 1}
                        </span>
                        <span className='min-w-0 flex-1 truncate text-std-16N-170 text-solid-gray-800'>
                          {info.label}
                          {info.path && info.path !== info.label && (
                            <span className='ml-2 text-dns-14N-130 text-solid-gray-500'>
                              {info.path}
                            </span>
                          )}
                          {!info.available && (
                            <span className='ml-2 text-dns-14N-130 text-error-1'>
                              （ファイルなし）
                            </span>
                          )}
                        </span>
                        <button
                          type='button'
                          onClick={() => moveItem(oi, ii, -1)}
                          disabled={ii === 0}
                          className='shrink-0 rounded-6 p-1 text-solid-gray-500 hover:bg-solid-gray-100 disabled:opacity-30'
                          title='上へ'
                        >
                          <PiArrowUp className='size-4' />
                        </button>
                        <button
                          type='button'
                          onClick={() => moveItem(oi, ii, 1)}
                          disabled={ii === out.items.length - 1}
                          className='shrink-0 rounded-6 p-1 text-solid-gray-500 hover:bg-solid-gray-100 disabled:opacity-30'
                          title='下へ'
                        >
                          <PiArrowDown className='size-4' />
                        </button>
                        <button
                          type='button'
                          onClick={() => removeItem(oi, ii)}
                          className='shrink-0 rounded-6 p-1 text-solid-gray-500 hover:bg-solid-gray-100 hover:text-error-1'
                          title='この章を除外'
                        >
                          <PiTrash className='size-4' />
                        </button>
                      </div>
                    );
                  })}
                  <div className='mt-1 flex items-center gap-2'>
                    <PiPlus className='size-4 shrink-0 text-solid-gray-500' />
                    <select
                      value=''
                      onChange={(e) => {
                        addItem(oi, e.target.value);
                        e.target.value = '';
                      }}
                      className='rounded-6 border border-solid-gray-300 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
                    >
                      <option value=''>章を追加…</option>
                      {sectionOptions.length > 0 && (
                        <optgroup label='章（生成）'>
                          {sectionOptions.map((s) => (
                            <option key={`sec:${s.key}`} value={`sec:${s.key}`}>
                              {s.label}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {fileOptions.length > 0 && (
                        <optgroup label='その他ファイル'>
                          {fileOptions.map((f) => (
                            <option key={`file:${f.id}`} value={`file:${f.id}`}>
                              {f.rel_path}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className='mt-3 flex items-center gap-2'>
          <input
            type='text'
            value={newOutputName}
            onChange={(e) => setNewOutputName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addOutput();
            }}
            className='w-64 rounded-6 border border-solid-gray-300 px-2 py-1 text-std-16N-170'
            placeholder='出力ファイルを追加（名称）'
          />
          <Button type='button' variant='outline' size='sm' onClick={addOutput}>
            <span className='inline-flex items-center gap-1'>
              <PiFilePlus className='size-4' />
              出力ファイルを追加
            </span>
          </Button>
        </div>

        <div className='mt-5 flex flex-wrap items-center gap-3 border-t border-solid-gray-200 pt-4'>
          <Button
            type='button'
            variant='outline'
            size='md'
            disabled={actions.submitting || !dirty}
            onClick={onSave}
          >
            <span className='inline-flex items-center gap-1'>
              <PiFloppyDisk className='size-4' />
              定義を保存
            </span>
          </Button>
          <Button
            type='button'
            variant='solid-fill'
            size='md'
            disabled={
              !composeConfigured ||
              actions.submitting ||
              compose.phase === 'running' ||
              enabledCount === 0
            }
            onClick={onCompose}
          >
            書き出す
          </Button>
          {savedNotice && (
            <span className='text-dns-14N-130 text-blue-700'>定義を保存しました。</span>
          )}
          {compose.phase === 'running' && (
            <span className='text-dns-14N-130 text-solid-gray-600'>合成中…</span>
          )}
          {compose.phase === 'error' && (
            <span className='text-dns-14N-130 text-error-1'>{compose.message}</span>
          )}
        </div>

        {compose.phase === 'done' && (
          <div className='mt-4 rounded-8 border border-blue-300 bg-blue-50 px-3 py-3 text-std-16N-170 text-solid-gray-800'>
            合成が完了しました{compose.names?.length ? `（${compose.names.join(' / ')}）` : ''}。
            {compose.url && (
              <Button
                type='button'
                variant='outline'
                size='sm'
                className='ml-3'
                onClick={() => triggerDownload(compose.url as string, compose.filename)}
              >
                ダウンロード
              </Button>
            )}
            {compose.skipped && compose.skipped.length > 0 && (
              <ul className='mt-2 list-disc pl-5 text-dns-14N-130 text-amber-800'>
                {compose.skipped.map((s) => (
                  <li key={s.name}>
                    {s.name}: {s.reason}（生成をスキップしました）
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
};

export const ProcuretechEditorPage = () => {
  const { config, unavailable } = useEditorConfig();
  const { projects, loadError: projectsError, mutate: mutateProjects } = useEditorProjects();
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
  const [previewStyle, setPreviewStyle] = useState<PreviewStyle>(() => {
    if (typeof window === 'undefined') return 'plain';
    const saved = window.localStorage.getItem(PREVIEW_STYLE_STORAGE_KEY);
    return saved === 'spec' || saved === 'numbered' || saved === 'plain' ? saved : 'plain';
  });
  const [savedNotice, setSavedNotice] = useState(false);
  const [fileModalOpen, setFileModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [pageError, setPageError] = useState<string | null>(null);

  // 画像挿入・AI 図生成の挿入先（ツールバーコマンド実行時の TextArea API を保持）。
  const insertApiRef = useRef<TextAreaTextApi | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  // プレビュー用: 相対パス画像 → presigned URL のマップ（表示専用、保存内容には影響しない）。
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({});

  // AI 図生成モーダルの状態。
  const [diagramOpen, setDiagramOpen] = useState(false);
  const [diagramDesc, setDiagramDesc] = useState('');
  const [diagramType, setDiagramType] = useState<'AI' | MermaidDiagramType>('AI');
  const [diagramBusy, setDiagramBusy] = useState(false);
  const [diagramError, setDiagramError] = useState<string | null>(null);

  // ヒアリングシート → 章別 Markdown 生成モーダルの状態（テーマ選択→入力の2ステップ）。
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generateStep, setGenerateStep] = useState<'theme' | 'inputs'>('theme');
  const [selectedTheme, setSelectedTheme] = useState<EditorGenerateTheme | null>(null);
  const [inputFiles, setInputFiles] = useState<Record<string, File | null>>({});
  const [generation, setGeneration] = useState<
    | { phase: 'idle' }
    | { phase: 'running'; requestId: string; progress?: number }
    | { phase: 'done'; files: string[] }
    | { phase: 'error'; message: string }
  >({ phase: 'idle' });
  const generateThemes = config?.generate_themes ?? [];
  const allInputsSelected = !!selectedTheme && selectedTheme.inputs.every((i) => inputFiles[i.key]);

  const tree = useMemo(() => buildTree(files), [files]);
  const selected = useMemo(
    () => files.find((f) => f.rel_path === selectedPath) ?? null,
    [files, selectedPath],
  );
  const isEditable = selected ? TEXT_KINDS.has(selected.kind) : false;
  const isMarkdown = selected?.kind === 'markdown';
  const isDirty = isEditable && draft !== baseline;
  const storageOk = config?.storage_configured !== false;

  // プレビュー・スタイルの選択を保存する（次回以降も維持）。
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PREVIEW_STYLE_STORAGE_KEY, previewStyle);
  }, [previewStyle]);

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

  // 生成ステータスのポーリング（成功時に ExApp 側が結果 zip を取り込む）。
  useEffect(() => {
    if (generation.phase !== 'running' || !projectId) return;
    const requestId = generation.requestId;
    let stop = false;
    const timer = window.setInterval(async () => {
      if (stop) return;
      try {
        const res = await fetchGeneration(projectId, requestId);
        const status = String(res.status ?? '').toLowerCase();
        if (status === 'success') {
          setGeneration({ phase: 'done', files: res.files ?? [] });
          await mutateProject();
          mutateProjects();
        } else if (status === 'error') {
          setGeneration({ phase: 'error', message: res.error || '生成に失敗しました。' });
        } else {
          setGeneration({ phase: 'running', requestId, progress: res.progress });
        }
      } catch (_e) {
        setGeneration({ phase: 'error', message: '生成状況の取得に失敗しました。' });
      }
    }, 2500);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [generation, projectId, mutateProject, mutateProjects]);

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
    if (
      !window.confirm(
        `プロジェクト「${name}」を削除しますか？（フォルダ内のファイルも削除されます）`,
      )
    ) {
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
    const res = await actions.saveFile(
      projectId,
      path,
      `# ${baseName(path).replace(/\.md$/, '')}\n\n`,
    );
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

  // 生成モーダルを開く（テーマ選択ステップから）。
  const onOpenGenerate = () => {
    setGeneration({ phase: 'idle' });
    setSelectedTheme(null);
    setInputFiles({});
    setGenerateStep('theme');
    setGenerateOpen(true);
  };

  // テーマを選び、入力（ヒアリングシート）ステップへ進む。
  const onPickTheme = (theme: EditorGenerateTheme) => {
    setSelectedTheme(theme);
    setInputFiles({});
    setGeneration({ phase: 'idle' });
    setGenerateStep('inputs');
  };

  // テーマ入力の様式（ヒアリングシート）を取得してダウンロードする。
  const onDownloadTemplate = async (inputKey: string) => {
    if (!selectedTheme) return;
    const res = await actions.downloadInputTemplate(selectedTheme.id, inputKey);
    if (res?.download_url) {
      window.open(res.download_url, '_blank', 'noopener');
    }
  };

  // 選択テーマのヒアリングシート（複数）から章別 Markdown 生成を開始する。
  const onStartGenerate = async () => {
    if (!projectId || !selectedTheme || !allInputsSelected) return;
    const inputs: Record<string, string> = {};
    for (const spec of selectedTheme.inputs) {
      const file = inputFiles[spec.key];
      if (!file) return;
      inputs[spec.key] = await fileToBase64(file);
    }
    setGeneration({ phase: 'idle' });
    const res = await actions.startGeneration(projectId, {
      theme: selectedTheme.id,
      inputs,
    });
    if (!res) return;
    if (res.request_id) {
      setGeneration({ phase: 'running', requestId: res.request_id });
    } else if (res.error) {
      setGeneration({ phase: 'error', message: res.error });
    } else {
      setGeneration({ phase: 'error', message: '生成を開始できませんでした。' });
    }
  };

  // --- 画像挿入 / AI 図生成 -----------------------------------------------
  // ツールバーコマンドが保持した TextArea API へ挿入する（無ければ末尾に追記）。
  const insertAtCursor = useCallback((text: string) => {
    const api = insertApiRef.current;
    if (api) {
      api.replaceSelection(text);
    } else {
      setDraft((d) => (d ? `${d}\n\n${text}` : text));
    }
  }, []);

  const onInsertImageClick = useCallback((api: TextAreaTextApi) => {
    insertApiRef.current = api;
    imageInputRef.current?.click();
  }, []);

  const onOpenDiagram = useCallback((api: TextAreaTextApi) => {
    insertApiRef.current = api;
    setDiagramError(null);
    setDiagramOpen(true);
  }, []);

  // 画像をプロジェクトフォルダ（images/）へアップロードし、相対パスで本文へ埋め込む。
  const onImagePicked = async (fileList: FileList | null) => {
    const file = fileList?.[0];
    if (!file || !projectId) return;
    const content_b64 = await fileToBase64(file);
    const f = await actions.uploadFile(projectId, {
      filename: file.name,
      content_b64,
      dir: 'images',
    });
    if (f) {
      await mutateProject();
      mutateProjects();
      const alt = baseName(f.rel_path).replace(/\.[^.]+$/, '');
      insertAtCursor(`![${alt}](${f.rel_path})`);
    }
  };

  // 既存「ダイアグラムを生成」と同じ genU predict + プロンプトで Mermaid を生成し、
  // ```mermaid ブロックとして本文へ挿入する（プレビューは Markdown 側で図描画）。
  const onGenerateDiagram = async () => {
    const desc = diagramDesc.trim();
    if (!desc) return;
    const modelId = resolveSelectedModelId();
    const model = modelId ? findModelByModelId(modelId) : undefined;
    if (!modelId || !model) {
      setDiagramError('利用可能な生成 AI モデルがありません。管理者に確認してください。');
      return;
    }
    setDiagramBusy(true);
    setDiagramError(null);
    try {
      const prompter = getPrompter(modelId);
      let type: MermaidDiagramType | 'AI' = diagramType;
      if (type === 'AI') {
        const selReq: PredictRequest = {
          model,
          id: 'procuretech-editor-diagram',
          messages: [
            { role: 'system', content: prompter.diagramPrompt({ determineType: true }) },
            { role: 'user', content: `<content>${desc}</content>` },
          ],
        };
        const sel = await predict(selReq);
        const cand = (sel.match(/<output>(.*?)<\/output>/i)?.[1] ?? '').toLowerCase().trim();
        const keys = Object.keys(MERMAID_DIAGRAM_TYPES) as MermaidDiagramType[];
        type = keys.find((k) => k === cand || cand.includes(k) || k.includes(cand)) ?? 'flowchart';
      }
      const req: PredictRequest = {
        model,
        id: 'procuretech-editor-diagram',
        messages: [
          {
            role: 'system',
            content: prompter.diagramPrompt({ determineType: false, diagramType: type }),
          },
          { role: 'user', content: `<content>${desc}</content>` },
        ],
      };
      const res = await predict(req);
      const code = extractDiagramCode(res);
      if (!code) {
        setDiagramError('図を生成できませんでした。説明を具体的にして再度お試しください。');
        return;
      }
      insertAtCursor(`\n\n\`\`\`mermaid\n${code}\n\`\`\`\n`);
      setDiagramOpen(false);
      setDiagramDesc('');
    } catch (_e) {
      setDiagramError('図の生成中にエラーが発生しました。時間をおいて再度お試しください。');
    } finally {
      setDiagramBusy(false);
    }
  };

  // ツールバーのコマンド一式（画像＝アップロード埋め込み、AI 図生成を含む）。
  const editorCommands = useMemo<ICommand[]>(() => {
    const imageCommand: ICommand = {
      name: 'image',
      keyCommand: 'image',
      buttonProps: { 'aria-label': '画像を挿入', title: '画像を挿入（アップロードして埋め込み）' },
      icon: <PiImage style={{ width: 16, height: 16 }} />,
      execute: (_state, api) => onInsertImageClick(api),
    };
    const diagramCommand: ICommand = {
      name: 'ai-diagram',
      keyCommand: 'ai-diagram',
      buttonProps: { 'aria-label': 'AI で図を生成', title: 'AI で図（Mermaid）を生成して挿入' },
      icon: <PiTreeStructure style={{ width: 16, height: 16 }} />,
      execute: (_state, api) => onOpenDiagram(api),
    };
    return [
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
      imageCommand,
      insertTable,
      diagramCommand,
      commands.divider,
      commands.unorderedListCommand,
      commands.orderedListCommand,
      commands.checkedListCommand,
    ];
  }, [onInsertImageClick, onOpenDiagram]);

  // プレビューに現れる相対パス画像の presigned URL を必要に応じて取得・キャッシュする。
  useEffect(() => {
    if (!projectId) return;
    const need = extractImageSources(draft).filter(
      (p) => !imageUrls[p] && files.some((f) => f.rel_path === p && f.kind === 'image'),
    );
    if (need.length === 0) return;
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        need.map(async (p) => {
          try {
            const c = await fetchFileContent(projectId, p);
            return [p, c.download_url ?? ''] as const;
          } catch {
            return [p, ''] as const;
          }
        }),
      );
      if (cancelled) return;
      const add = Object.fromEntries(entries.filter(([, u]) => u));
      if (Object.keys(add).length > 0) {
        setImageUrls((prev) => ({ ...prev, ...add }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [draft, files, projectId, imageUrls]);

  // 保存内容は相対パスのまま。プレビュー時だけ presigned URL へ差し替える。
  const previewSource = useMemo(
    () => rewriteImageSources(draft || '（本文がありません）', imageUrls),
    [draft, imageUrls],
  );

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
      <PageTitle title='Markdown エディタ' />

      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'>
        <div className='flex flex-col gap-1'>
          <h1 className='text-std-22B-150 text-solid-gray-900'>Markdown エディタ</h1>
          <p className='text-dns-16N-170 text-solid-gray-700'>
            プロジェクト内の文書（Markdown）を編集・校正し、Word 文書へ統合する準備を行います。
          </p>
        </div>

        {unavailable && (
          <div
            className='rounded-8 border border-amber-300 bg-amber-50 px-4 py-2 text-dns-14N-130 text-solid-gray-800'
            role='status'
          >
            Markdown エディタは現在利用できません（サービス未起動）。
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
              <h2 className='text-std-18B-160 text-solid-gray-900'>プロジェクト一覧</h2>
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
            「プロジェクト選択」タブからプロジェクトを開いてください。
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

              {config?.generate_configured !== false && (
                <Button type='button' variant='outline' size='sm' onClick={onOpenGenerate}>
                  <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                    <PiTable className='size-4' />
                    ヒアリングシートから生成
                  </span>
                </Button>
              )}

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
                {isMarkdown && viewMode !== 'edit' && (
                  <label className='flex items-center gap-1 text-dns-14N-130 text-solid-gray-700'>
                    <span className='whitespace-nowrap'>プレビュー表示</span>
                    <select
                      value={previewStyle}
                      onChange={(e) => setPreviewStyle(e.target.value as PreviewStyle)}
                      className='rounded-4 border border-solid-gray-300 bg-white px-2 py-1 text-dns-14N-130'
                      title='プレビューの見出し・表スタイル（表示専用）'
                    >
                      {PREVIEW_STYLE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
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
                      commands={editorCommands}
                      extraCommands={EDITOR_EXTRA_COMMANDS}
                    />
                  </div>
                )}
                {isMarkdown && viewMode !== 'edit' && (
                  <div
                    ref={previewRef}
                    className='h-full overflow-auto rounded-8 border border-solid-gray-300 bg-white p-4'
                  >
                    <Markdown className={previewStyleClass(previewStyle)}>{previewSource}</Markdown>
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {activeTab === EXPORT_TAB && !project && (
          <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
            「プロジェクト選択」タブからプロジェクトを開いてください。
          </div>
        )}

        {activeTab === EXPORT_TAB && project && <CompositionEditor projectId={project.id} />}
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

      {/* 画像挿入用の隠しファイル入力（ツールバーの画像ボタンから呼ぶ）。 */}
      <input
        ref={imageInputRef}
        type='file'
        accept='image/*'
        className='sr-only'
        onChange={(e) => {
          onImagePicked(e.target.files);
          if (imageInputRef.current) imageInputRef.current.value = '';
        }}
      />

      {/* AI 図（Mermaid）生成モーダル。 */}
      <CustomDialog
        isOpen={diagramOpen}
        onClose={() => (diagramBusy ? undefined : setDiagramOpen(false))}
      >
        <CustomDialogPanel className='max-w-xl'>
          <CustomDialogHeader hasClose onClose={() => setDiagramOpen(false)}>
            <span className='inline-flex items-center gap-2'>
              <PiTreeStructure className='size-6 text-solid-gray-700' />
              AI で図を生成（Mermaid）
            </span>
          </CustomDialogHeader>
          <CustomDialogBody>
            <div className='flex flex-col gap-3'>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                図の種類
                <select
                  value={diagramType}
                  disabled={diagramBusy}
                  onChange={(e) => setDiagramType(e.target.value as 'AI' | MermaidDiagramType)}
                  className='rounded-8 border border-solid-gray-300 px-3 py-2 text-std-16N-170'
                >
                  {DIAGRAM_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                図にしたい内容の説明
                <textarea
                  value={diagramDesc}
                  disabled={diagramBusy}
                  onChange={(e) => setDiagramDesc(e.target.value)}
                  rows={6}
                  placeholder='例）調達の申請から契約締結までの承認フローを図にして。差し戻しの分岐も含める。'
                  className='rounded-8 border border-solid-gray-300 px-3 py-2 text-std-16N-170'
                />
              </label>
              {diagramError && (
                <p className='rounded-8 border border-error-2 bg-error-3 px-3 py-2 text-dns-14N-130 text-error-1'>
                  {diagramError}
                </p>
              )}
              <p className='text-dns-14N-130 text-solid-gray-600'>
                生成された Mermaid はカーソル位置に挿入され、プレビューに図として表示されます。
              </p>
              <div className='mt-1 flex items-center justify-end gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='md'
                  disabled={diagramBusy}
                  onClick={() => setDiagramOpen(false)}
                >
                  キャンセル
                </Button>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='md'
                  disabled={diagramBusy || !diagramDesc.trim()}
                  onClick={onGenerateDiagram}
                >
                  <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                    <PiMagicWand className='size-4' />
                    {diagramBusy ? '生成中…' : '生成して挿入'}
                  </span>
                </Button>
              </div>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>

      {/* ヒアリングシート → 章別 Markdown 生成モーダル（テーマ選択 → 入力）。 */}
      <CustomDialog
        isOpen={generateOpen}
        onClose={() => (generation.phase === 'running' ? undefined : setGenerateOpen(false))}
      >
        <CustomDialogPanel className='max-w-xl'>
          <CustomDialogHeader hasClose onClose={() => setGenerateOpen(false)}>
            <span className='inline-flex items-center gap-2'>
              <PiTable className='size-6 text-solid-gray-700' />
              ヒアリングシートから生成
            </span>
          </CustomDialogHeader>
          <CustomDialogBody>
            <div className='flex flex-col gap-3'>
              {config?.generate_configured === false && (
                <p className='rounded-8 border border-amber-300 bg-amber-50 px-3 py-2 text-dns-14N-130 text-solid-gray-800'>
                  文書生成 API が未設定です。管理者に設定を依頼してください。
                </p>
              )}

              {generateStep === 'theme' && (
                <>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    生成する文書のテーマを選択してください。テーマごとに、必要なヒアリングシートと呼び出す生成
                    API が異なります。
                  </p>
                  {generateThemes.length === 0 ? (
                    <p className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-3 py-3 text-dns-14N-130 text-solid-gray-600'>
                      利用可能なテーマがありません。管理者にテーマ設定（EDITOR_GENERATE_THEMES）を依頼してください。
                    </p>
                  ) : (
                    <ul className='flex flex-col gap-2'>
                      {generateThemes.map((t) => (
                        <li key={t.id}>
                          <button
                            type='button'
                            disabled={t.configured === false}
                            onClick={() => onPickTheme(t)}
                            className='flex w-full flex-col items-start gap-0.5 rounded-8 border border-solid-gray-300 bg-white px-3 py-2 text-left hover:border-blue-400 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50'
                          >
                            <span className='inline-flex items-center gap-2 text-std-16B-150 text-solid-gray-900'>
                              <PiFileText className='size-4 text-solid-gray-600' />
                              {t.label}
                              {t.configured === false && (
                                <span className='rounded-full bg-amber-100 px-2 py-0.5 text-dns-14N-130 text-amber-800'>
                                  API 未設定
                                </span>
                              )}
                            </span>
                            {t.description && (
                              <span className='text-dns-14N-130 text-solid-gray-600'>
                                {t.description}
                              </span>
                            )}
                            <span className='text-dns-14N-130 text-solid-gray-500'>
                              必要なシート: {t.inputs.map((i) => i.label).join(' / ') || '—'}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className='mt-1 flex items-center justify-end'>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      onClick={() => setGenerateOpen(false)}
                    >
                      キャンセル
                    </Button>
                  </div>
                </>
              )}

              {generateStep === 'inputs' && selectedTheme && (
                <>
                  <div className='flex flex-wrap items-center gap-2 text-dns-14N-130'>
                    <span className='rounded-full bg-blue-100 px-2 py-0.5 text-blue-900'>
                      {selectedTheme.label}
                    </span>
                    {selectedTheme.description && (
                      <span className='text-solid-gray-600'>{selectedTheme.description}</span>
                    )}
                  </div>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    必要なヒアリングシートをアップロードすると、章別の Markdown
                    を生成し、このプロジェクトへ取り込みます。
                  </p>
                  {selectedTheme.inputs.map((spec) => {
                    const picked = inputFiles[spec.key];
                    const busy = generation.phase === 'running';
                    return (
                      <div key={spec.key} className='flex flex-col gap-1'>
                        <span className='text-dns-14N-130 text-solid-gray-700'>{spec.label}</span>
                        <div className='flex items-center gap-2'>
                          <label
                            className={
                              busy
                                ? 'inline-flex cursor-not-allowed items-center gap-1 rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-3 py-1.5 text-dns-14N-130 text-solid-gray-400'
                                : 'inline-flex cursor-pointer items-center gap-1 rounded-8 border border-solid-gray-300 bg-white px-3 py-1.5 text-dns-14N-130 text-solid-gray-800 hover:bg-solid-gray-50'
                            }
                          >
                            <PiUploadSimple className='size-4' />
                            ファイルを選択
                            <input
                              type='file'
                              accept={spec.accept || '.xlsx'}
                              className='sr-only'
                              disabled={busy}
                              onChange={(e) => {
                                const f = e.target.files?.[0] ?? null;
                                setInputFiles((prev) => ({ ...prev, [spec.key]: f }));
                                setGeneration({ phase: 'idle' });
                              }}
                            />
                          </label>
                          <span className='min-w-0 truncate text-dns-14N-130 text-solid-gray-500'>
                            {picked ? picked.name : '未選択'}
                          </span>
                        </div>
                        {spec.template && (
                          <button
                            type='button'
                            onClick={() => onDownloadTemplate(spec.key)}
                            disabled={actions.submitting}
                            className='inline-flex w-fit items-center gap-1 text-dns-14N-130 text-blue-700 underline-offset-2 hover:underline disabled:text-solid-gray-400'
                            title='この入力の様式（ヒアリングシート）をダウンロード'
                          >
                            <PiDownloadSimple className='size-4' />
                            様式をダウンロード
                          </button>
                        )}
                      </div>
                    );
                  })}
                  {generation.phase === 'running' && (
                    <p className='rounded-8 border border-blue-300 bg-blue-50 px-3 py-2 text-dns-14N-130 text-solid-gray-800'>
                      生成中です。しばらくお待ちください…
                      {typeof generation.progress === 'number' ? `（${generation.progress}%）` : ''}
                    </p>
                  )}
                  {generation.phase === 'error' && (
                    <p className='rounded-8 border border-error-2 bg-error-3 px-3 py-2 text-dns-14N-130 text-error-1'>
                      {generation.message}
                    </p>
                  )}
                  {generation.phase === 'done' && (
                    <div className='rounded-8 border border-blue-300 bg-blue-50 px-3 py-2 text-dns-14N-130 text-solid-gray-800'>
                      {generation.files.length}件のファイルを取り込みました。
                      {generation.files.length > 0 && (
                        <ul className='mt-1 list-disc pl-5'>
                          {generation.files.map((p) => (
                            <li key={p}>{p}</li>
                          ))}
                        </ul>
                      )}
                      <p className='mt-1 text-solid-gray-600'>
                        「ファイル管理」から開いて編集できます。
                      </p>
                    </div>
                  )}
                  <div className='mt-1 flex items-center justify-between gap-2'>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      disabled={generation.phase === 'running'}
                      onClick={() => setGenerateStep('theme')}
                    >
                      戻る
                    </Button>
                    <div className='flex items-center gap-2'>
                      <Button
                        type='button'
                        variant='outline'
                        size='md'
                        disabled={generation.phase === 'running'}
                        onClick={() => setGenerateOpen(false)}
                      >
                        {generation.phase === 'done' ? '閉じる' : 'キャンセル'}
                      </Button>
                      <Button
                        type='button'
                        variant='solid-fill'
                        size='md'
                        disabled={
                          selectedTheme.configured === false ||
                          !allInputsSelected ||
                          actions.submitting ||
                          generation.phase === 'running' ||
                          generation.phase === 'done'
                        }
                        onClick={onStartGenerate}
                      >
                        <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                          <PiMagicWand className='size-4' />
                          {generation.phase === 'running'
                            ? '生成中…'
                            : generation.phase === 'done'
                              ? '取り込み済み'
                              : '生成して取り込み'}
                        </span>
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};
