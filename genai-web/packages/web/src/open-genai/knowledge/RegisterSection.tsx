import { type Dispatch, type SetStateAction, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { convertFileToBase64 } from '@/features/exapp/utils/convertFileToBase64';
import { Notice, useNotice } from './Notice';
import { mergeTags, TagPicker } from './TagPicker';
import type { KnowledgeTag, RegisterMode, UploadFile } from './types';
import { registerFiles, registerUrl } from './useKnowledge';

const ACCEPT = '.pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json';

type Props = {
  scope: string;
  tags: KnowledgeTag[];
  mutateTags: () => void;
  mutateDocs: () => void;
};

export const RegisterSection = ({ scope, tags, mutateTags, mutateDocs }: Props) => {
  const { notice, success, fail, clear } = useNotice();
  const [busy, setBusy] = useState(false);

  // ---- ファイル登録 ----
  const [mode, setMode] = useState<RegisterMode>('tree');
  const [files, setFiles] = useState<File[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [newTagsText, setNewTagsText] = useState('');

  // ---- URL 登録 ----
  const [url, setUrl] = useState('');
  const [urlSelected, setUrlSelected] = useState<string[]>([]);
  const [urlNewTagsText, setUrlNewTagsText] = useState('');

  const toggle = (setter: Dispatch<SetStateAction<string[]>>) => (tag: string) =>
    setter((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));

  const handleRegisterFiles = async () => {
    clear();
    if (files.length === 0) {
      fail(new Error('登録するファイルを選択してください。'), '');
      return;
    }
    setBusy(true);
    try {
      const uploads: UploadFile[] = await Promise.all(
        files.map(async (f) => ({
          filename: f.name,
          content: await convertFileToBase64(f),
          media_type: f.type || '',
        })),
      );
      const res = await registerFiles(scope, mode, mergeTags(selected, newTagsText), uploads);
      const count = res.documents?.length ?? 0;
      success(`${count} 件のドキュメントを登録しました。`);
      setFiles([]);
      setSelected([]);
      setNewTagsText('');
      mutateTags();
      mutateDocs();
    } catch (e) {
      fail(e, 'ドキュメントの登録に失敗しました。');
    } finally {
      setBusy(false);
    }
  };

  const handleRegisterUrl = async () => {
    clear();
    if (!url.trim()) return;
    setBusy(true);
    try {
      await registerUrl(scope, url.trim(), mergeTags(urlSelected, urlNewTagsText));
      success(`URL を登録しました。`);
      setUrl('');
      setUrlSelected([]);
      setUrlNewTagsText('');
      mutateTags();
      mutateDocs();
    } catch (e) {
      fail(e, 'URL の登録に失敗しました。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className='flex flex-col gap-8'>
      <Notice notice={notice} />

      <section className='flex flex-col gap-3'>
        <h2 className='text-std-18B-160'>ファイルを登録</h2>
        <SupportText>対応形式: {ACCEPT}</SupportText>

        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='reg-mode' size='sm'>
            取り込み方式
          </Label>
          <Select
            id='reg-mode'
            blockSize='md'
            value={mode}
            onChange={(e) => setMode(e.target.value as RegisterMode)}
            className='max-w-md'
          >
            <option value='tree'>標準（ツリー索引 + ベクトル。目次のある資料向け）</option>
            <option value='fulltext'>簡易（全文 + ベクトル。短い資料向け）</option>
          </Select>
        </div>

        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='reg-files' size='sm'>
            ファイル
          </Label>
          <input
            id='reg-files'
            type='file'
            multiple
            accept={ACCEPT}
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className='text-oln-16N-100'
          />
          {files.length > 0 && (
            <p className='text-dns-14N-130 text-solid-gray-600'>選択中: {files.length} 件</p>
          )}
        </div>

        <TagPicker
          idPrefix='reg'
          tags={tags}
          selected={selected}
          onToggle={toggle(setSelected)}
          newTagsText={newTagsText}
          onNewTagsText={setNewTagsText}
        />

        <div>
          <Button
            variant='solid-fill'
            size='md'
            aria-disabled={busy || files.length === 0 || undefined}
            onClick={() => void handleRegisterFiles()}
          >
            {busy ? '登録中…' : '登録する'}
          </Button>
        </div>
      </section>

      <section className='flex flex-col gap-3 border-t border-solid-gray-300 pt-6'>
        <h2 className='text-std-18B-160'>URL を登録</h2>
        <SupportText>Web ページの本文を取り込みます。定期的に自動で再取得されます。</SupportText>

        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='reg-url' size='sm'>
            URL
          </Label>
          <Input
            id='reg-url'
            type='url'
            placeholder='https://example.com/page'
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className='max-w-full'
          />
        </div>

        <TagPicker
          idPrefix='reg-url'
          tags={tags}
          selected={urlSelected}
          onToggle={toggle(setUrlSelected)}
          newTagsText={urlNewTagsText}
          onNewTagsText={setUrlNewTagsText}
        />

        <div>
          <Button
            variant='outline'
            size='md'
            aria-disabled={busy || !url.trim() || undefined}
            onClick={() => void handleRegisterUrl()}
          >
            URL を登録
          </Button>
        </div>
      </section>
    </div>
  );
};
