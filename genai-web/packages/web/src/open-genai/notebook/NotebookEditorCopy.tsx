import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { teamApi } from '@/lib/fetcher';
import {
  useEditorActions,
  useEditorProjects,
} from '@/open-genai/procuretech-editor/useProcuretechEditor';
import type { EditorFile } from '@/open-genai/procuretech-editor/types';
import type { NotebookFile, NotebookItem } from './types';

type Props = {
  sessionId: string;
  files: NotebookFile[];
  items: NotebookItem[];
};

const isImageName = (name: string) => /\.(png|jpe?g|webp|gif)$/i.test(name);

const uniqueName = (name: string, taken: Set<string>) => {
  if (!taken.has(name)) return name;
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : '';
  let n = 2;
  while (taken.has(`${stem}-${n}${ext}`) && n < 100) n += 1;
  return `${stem}-${n}${ext}`;
};

const decodeText = (b64: string) => {
  const binary = atob(b64);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
};

const clipMarkdown = (items: NotebookItem[]) => {
  const filled = items.filter((item) => item.label.trim() || item.value.trim());
  if (!filled.length) return '';
  const lines = ['# クリップ', ''];
  for (const item of filled) {
    lines.push(`## ${item.label.trim() || 'クリップ'}`, '', item.value.trim(), '');
  }
  return lines.join('\n');
};

export const NotebookEditorCopy = ({ sessionId, files, items }: Props) => {
  const navigate = useNavigate();
  const { projects } = useEditorProjects();
  const actions = useEditorActions();
  const [selected, setSelected] = useState<string[]>(() => files.map((file) => file.id));
  const [projectId, setProjectId] = useState('');
  const [newName, setNewName] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const clips = clipMarkdown(items);
  const copy = async () => {
    const chosen = files.filter((file) => selected.includes(file.id) && !file.error);
    if (!chosen.length && !clips) {
      setError('コピーする資料を選んでください。');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      let target = projectId;
      if (!target) {
        const created = await actions.createProject(newName.trim() || 'ノートの資料');
        target = created?.id ?? '';
      }
      if (!target) {
        setError('プロジェクトを用意できませんでした。');
        return;
      }
      const listed = await teamApi.get<{ files?: EditorFile[] }>(
        `procuretech-editor/projects/${encodeURIComponent(target)}`,
      );
      const taken = new Set(
        (listed.data?.files ?? []).map((file) => file.rel_path.replace(/^images\//, '')),
      );
      const embeds: string[] = ['# ノートから持ち込んだ資料', ''];
      for (const file of chosen) {
        const got = await teamApi.get<{ filename: string; content: string }>(
          `notebook/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(file.id)}/content`,
        );
        const filename = uniqueName(got.data?.filename || file.filename, taken);
        const content = got.data?.content ?? '';
        taken.add(filename);
        if (isImageName(filename)) {
          const saved = await actions.uploadFile(target, {
            filename,
            content_b64: content,
            dir: 'images',
          });
          if (!saved) {
            setError('画像をプロジェクトへ置けませんでした。');
            return;
          }
          embeds.push(`## ${filename}`, '', `![${filename}](images/${filename})`, '');
          continue;
        }
        const text = decodeText(content);
        const saved = await actions.saveFile(target, filename, text);
        if (!saved) {
          setError('ファイルをプロジェクトへ置けませんでした。');
          return;
        }
        if (text.includes('```mermaid')) {
          embeds.push(text.trim(), '');
        }
      }
      if (clips) {
        const clipName = uniqueName('クリップ.md', taken);
        const saved = await actions.saveFile(target, clipName, clips);
        if (!saved) {
          setError('クリップをプロジェクトへ置けませんでした。');
          return;
        }
        taken.add(clipName);
        embeds.push(clips.trim(), '');
      }
      const indexName = uniqueName('ノートの資料.md', taken);
      const index = await actions.saveFile(target, indexName, embeds.join('\n'));
      if (!index) {
        setError('まとめの原稿を置けませんでした。');
        return;
      }
      setNotice(`プロジェクトへコピーしました。${indexName} を開きます。`);
      navigate(
        `/procuretech-editor?project=${encodeURIComponent(target)}&file=${encodeURIComponent(indexName)}`,
      );
    } catch {
      setError('コピーできませんでした。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto py-4'>
      <h2 className='text-std-18B-160 text-solid-gray-900'>Markdown エディタへコピー</h2>
      <p className='text-dns-14N-130 text-solid-gray-600'>
        選んだ参考資料とクリップを、指定したプロジェクトへ置きます。同じ名前のファイルがあっても上書きせず、末尾に
        -2 を付けて追加します。画像は images に入り、図の Mermaid とクリップの本文はそのまま原稿に入ります。
      </p>
      {files.length === 0 ? (
        <p className='text-dns-14N-130 text-solid-gray-600'>まだ参考資料のファイルがありません。</p>
      ) : (
        <ul className='flex flex-col gap-2'>
          {files.map((file) => (
            <li key={file.id}>
              <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-800'>
                <input
                  type='checkbox'
                  checked={selected.includes(file.id)}
                  onChange={(event) =>
                    setSelected((prev) =>
                      event.target.checked
                        ? [...prev, file.id]
                        : prev.filter((id) => id !== file.id),
                    )
                  }
                />
                <span className='break-all'>{file.filename}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className='flex flex-col gap-2'>
        <Label htmlFor='notebook-editor-project'>既存のプロジェクト</Label>
        <Select
          id='notebook-editor-project'
          blockSize='md'
          value={projectId}
          onChange={(event) => setProjectId(event.target.value)}
        >
          <option value=''>新しく作る</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name || '無題'}
            </option>
          ))}
        </Select>
        {!projectId ? (
          <>
            <Label htmlFor='notebook-editor-new'>新しいプロジェクト名</Label>
            <Input
              id='notebook-editor-new'
              value={newName}
              placeholder='ノートの資料'
              onChange={(event) => setNewName(event.target.value)}
            />
          </>
        ) : null}
      </div>
      {error ? <ErrorText>{error}</ErrorText> : null}
      {notice ? <p className='text-dns-14N-130 text-solid-gray-700'>{notice}</p> : null}
      <div>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          aria-disabled={busy || (files.length === 0 && !clips) || undefined}
          onClick={() => void copy()}
        >
          {busy ? 'コピーしています...' : clips ? '選んだ資料とクリップをコピー' : '選んだ資料をコピー'}
        </Button>
      </div>
    </section>
  );
};
