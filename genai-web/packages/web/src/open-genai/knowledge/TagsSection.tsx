import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { ChipLabel } from '@/components/ui/dads/ChipLabel';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Textarea } from '@/components/ui/dads/Textarea';
import { Notice, useNotice } from './Notice';
import type { KnowledgeTag } from './types';
import { createTag, deleteTag, renameTag, updateTagDescription } from './useKnowledge';

type Props = {
  scope: string;
  canManage: boolean;
  tags: KnowledgeTag[];
  mutateTags: () => void;
};

const TagDescriptionField = ({
  scope,
  tag,
  description,
  canManage,
  busy,
  onSave,
}: {
  scope: string;
  tag: string;
  description: string;
  canManage: boolean;
  busy: boolean;
  onSave: (tag: string, description: string) => Promise<void>;
}) => {
  const [value, setValue] = useState(description);
  useEffect(() => setValue(description), [description]);
  if (!canManage) {
    return description ? (
      <p className='text-dns-14N-130 text-solid-gray-700'>{description}</p>
    ) : null;
  }
  const dirty = value.trim() !== description.trim();
  return (
    <div className='flex flex-col gap-1.5'>
      <Label htmlFor={`tag-description-${scope}-${tag}`} size='sm'>
        説明
      </Label>
      <Textarea
        id={`tag-description-${scope}-${tag}`}
        rows={2}
        maxLength={400}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder='このタグが何の資料かを書きます。ノートの参考資料に表示されます。'
      />
      <div className='flex items-center justify-between gap-3'>
        <SupportText>{value.trim().length}/400</SupportText>
        <Button
          variant='outline'
          size='sm'
          aria-disabled={busy || !dirty || undefined}
          onClick={() => {
            if (busy || !dirty) return;
            void onSave(tag, value.trim());
          }}
        >
          説明を保存
        </Button>
      </div>
    </div>
  );
};

export const TagsSection = ({ scope, canManage, tags, mutateTags }: Props) => {
  const { notice, success, fail, clear } = useNotice();
  const [newTag, setNewTag] = useState('');
  const [renameFrom, setRenameFrom] = useState('');
  const [renameTo, setRenameTo] = useState('');
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, ok: string, ng: string) => {
    clear();
    setBusy(true);
    try {
      await fn();
      success(ok);
      mutateTags();
    } catch (e) {
      fail(e, ng);
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = () => {
    if (!newTag.trim()) return;
    void run(
      async () => {
        await createTag(scope, newTag.trim());
        setNewTag('');
      },
      `タグ「${newTag.trim()}」を作成しました。`,
      'タグの作成に失敗しました。',
    );
  };

  const handleRename = () => {
    if (!renameFrom || !renameTo.trim()) return;
    void run(
      async () => {
        await renameTag(scope, renameFrom, renameTo.trim());
        setRenameTo('');
      },
      `タグを「${renameTo.trim()}」に変更しました。`,
      'タグ名の変更に失敗しました。',
    );
  };

  const handleDelete = (tag: string) => {
    void run(
      () => deleteTag(scope, tag),
      `タグ「${tag}」を削除しました。`,
      'タグの削除に失敗しました。',
    );
  };

  const handleDescribe = (tag: string, description: string) =>
    run(
      () => updateTagDescription(scope, tag, description),
      `タグ「${tag}」の説明を保存しました。`,
      '説明の保存に失敗しました。',
    );

  return (
    <div className='flex flex-col gap-6'>
      <Notice notice={notice} />

      <section className='flex flex-col gap-3'>
        <h2 className='text-std-18B-160'>タグ一覧</h2>
        <SupportText>
          タグが付いた資料のみ検索対象になります。説明はノートの参考資料に表示されます。未使用（0
          チャンク）のタグは削除できます。
        </SupportText>
        {tags.length === 0 ? (
          <p className='text-solid-gray-600'>タグはまだありません。</p>
        ) : (
          <ul className='flex flex-col divide-y divide-solid-gray-300 rounded-8 border border-solid-gray-300'>
            {tags.map((t) => (
              <li key={t.tag} className='flex flex-col gap-2 px-4 py-3'>
                <span className='flex items-center justify-between gap-3'>
                  <span className='flex items-center gap-2'>
                    <ChipLabel className='bg-blue-50 text-blue-900'>{t.tag}</ChipLabel>
                    <span className='text-dns-14N-130 text-solid-gray-600'>
                      {t.chunks > 0 ? `${t.chunks} チャンク` : '未使用（検索対象外）'}
                    </span>
                  </span>
                  {canManage && (
                    <Button
                      variant='text'
                      size='sm'
                      aria-disabled={busy || t.chunks > 0 || undefined}
                      title={t.chunks > 0 ? '使用中のタグは削除できません' : undefined}
                      onClick={() => handleDelete(t.tag)}
                    >
                      削除
                    </Button>
                  )}
                </span>
                <TagDescriptionField
                  scope={scope}
                  tag={t.tag}
                  description={t.description ?? ''}
                  canManage={canManage}
                  busy={busy}
                  onSave={handleDescribe}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      {canManage && (
        <>
          <section className='flex flex-col gap-2'>
            <h2 className='text-std-18B-160'>タグを作成</h2>
            <div className='flex flex-wrap items-end gap-3'>
              <div className='flex flex-col gap-1.5'>
                <Label htmlFor='new-tag' size='sm'>
                  新しいタグ名
                </Label>
                <Input
                  id='new-tag'
                  type='text'
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                  className='min-w-64'
                />
              </div>
              <Button
                variant='solid-fill'
                size='md'
                aria-disabled={busy || !newTag.trim() || undefined}
                onClick={handleCreate}
              >
                作成
              </Button>
            </div>
          </section>

          <section className='flex flex-col gap-2'>
            <h2 className='text-std-18B-160'>タグ名を変更</h2>
            <div className='flex flex-wrap items-end gap-3'>
              <div className='flex flex-col gap-1.5'>
                <Label htmlFor='rename-from' size='sm'>
                  変更するタグ
                </Label>
                <Select
                  id='rename-from'
                  blockSize='md'
                  value={renameFrom}
                  onChange={(e) => setRenameFrom(e.target.value)}
                  className='min-w-64'
                >
                  <option value=''>選択してください</option>
                  {tags.map((t) => (
                    <option key={t.tag} value={t.tag}>
                      {t.tag}
                    </option>
                  ))}
                </Select>
              </div>
              <div className='flex flex-col gap-1.5'>
                <Label htmlFor='rename-to' size='sm'>
                  新しいタグ名
                </Label>
                <Input
                  id='rename-to'
                  type='text'
                  value={renameTo}
                  onChange={(e) => setRenameTo(e.target.value)}
                  className='min-w-64'
                />
              </div>
              <Button
                variant='outline'
                size='md'
                aria-disabled={busy || !renameFrom || !renameTo.trim() || undefined}
                onClick={handleRename}
              >
                変更
              </Button>
            </div>
          </section>
        </>
      )}
    </div>
  );
};
