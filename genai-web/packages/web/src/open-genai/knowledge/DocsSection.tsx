import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { ChipLabel } from '@/components/ui/dads/ChipLabel';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Notice, useNotice } from './Notice';
import { mergeTags, TagPicker } from './TagPicker';
import type { KnowledgeDoc, KnowledgeTag } from './types';
import { clearScope, deleteDoc, refreshUrls, retagDoc } from './useKnowledge';

type Props = {
  scope: string;
  canManage: boolean;
  isSystemAdmin: boolean;
  tags: KnowledgeTag[];
  docs: KnowledgeDoc[];
  mutateDocs: () => void;
  mutateTags: () => void;
};

const isUrl = (s: string) => s.startsWith('http://') || s.startsWith('https://');

export const DocsSection = ({
  scope,
  canManage,
  isSystemAdmin,
  tags,
  docs,
  mutateDocs,
  mutateTags,
}: Props) => {
  const { notice, success, fail, clear } = useNotice();
  const [busy, setBusy] = useState(false);
  const [filterTag, setFilterTag] = useState('');
  const [retagFor, setRetagFor] = useState<string | null>(null);
  const [retagSelected, setRetagSelected] = useState<string[]>([]);
  const [retagNewText, setRetagNewText] = useState('');

  const visibleDocs = filterTag
    ? docs.filter((d) => (d.tags ?? []).includes(filterTag))
    : docs;

  const openRetag = (doc: KnowledgeDoc) => {
    clear();
    setRetagFor(doc.source);
    setRetagSelected(doc.tags ?? []);
    setRetagNewText('');
  };

  const run = async (fn: () => Promise<unknown>, ok: string, ng: string) => {
    clear();
    setBusy(true);
    try {
      await fn();
      success(ok);
      mutateDocs();
      mutateTags();
    } catch (e) {
      fail(e, ng);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = (source: string) => {
    if (!window.confirm(`「${source}」をナレッジから削除します。よろしいですか？`)) return;
    void run(() => deleteDoc(scope, source), `「${source}」を削除しました。`, '削除に失敗しました。');
  };

  const handleRetagSave = (source: string) => {
    const finalTags = mergeTags(retagSelected, retagNewText);
    if (finalTags.length === 0) {
      fail(new Error('タグを1つ以上指定してください。'), '');
      return;
    }
    void run(
      async () => {
        await retagDoc(scope, source, finalTags);
        setRetagFor(null);
      },
      `「${source}」のタグを更新しました。`,
      'タグの更新に失敗しました。',
    );
  };

  const handleRefreshUrls = () => {
    void run(
      () => refreshUrls(scope),
      '登録済み URL を再取得しました（変更分のみ更新）。',
      'URL の再取得に失敗しました。',
    );
  };

  const handleClear = () => {
    if (
      !window.confirm(
        'このスコープのナレッジ（ドキュメント・URL・タグ）をすべて消去します。元に戻せません。よろしいですか？',
      )
    )
      return;
    void run(() => clearScope(scope), 'ナレッジを全消去しました。', '全消去に失敗しました。');
  };

  return (
    <div className='flex flex-col gap-4'>
      <Notice notice={notice} />

      <div className='flex flex-wrap items-end justify-between gap-3'>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='docs-filter' size='sm'>
            タグで絞り込み
          </Label>
          <Select
            id='docs-filter'
            blockSize='sm'
            value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)}
            className='min-w-56'
          >
            <option value=''>すべて</option>
            {tags.map((t) => (
              <option key={t.tag} value={t.tag}>
                {t.tag}
              </option>
            ))}
          </Select>
        </div>
        {isSystemAdmin && (
          <div className='flex flex-wrap gap-2'>
            <Button
              variant='outline'
              size='sm'
              aria-disabled={busy || undefined}
              onClick={handleRefreshUrls}
            >
              URL を再取得
            </Button>
            <Button
              variant='outline'
              size='sm'
              className='border-error-1 text-error-2'
              aria-disabled={busy || undefined}
              onClick={handleClear}
            >
              全消去
            </Button>
          </div>
        )}
      </div>

      {visibleDocs.length === 0 ? (
        <p className='text-solid-gray-600'>登録済みのドキュメントはありません。</p>
      ) : (
        <ul className='flex flex-col divide-y divide-solid-gray-300 rounded-8 border border-solid-gray-300'>
          {visibleDocs.map((d) => (
            <li key={d.doc_id || d.source} className='flex flex-col gap-2 px-4 py-3'>
              <div className='flex flex-wrap items-start justify-between gap-3'>
                <div className='flex flex-col gap-1'>
                  <span className='flex flex-wrap items-center gap-2 text-oln-16N-100 break-all'>
                    <ChipLabel className='bg-solid-gray-100 text-solid-gray-800'>
                      {isUrl(d.source) ? 'URL' : d.index_kind === 'tree' ? '構造化' : '全文'}
                    </ChipLabel>
                    {(d.ingest_status === 'queued' || d.ingest_status === 'processing') && (
                      <ChipLabel className='bg-solid-gray-200 text-solid-gray-800'>
                        {d.ingest_status === 'queued' ? '登録待ち' : '登録中'}
                      </ChipLabel>
                    )}
                    {d.ingest_status === 'failed' && (
                      <ChipLabel className='bg-red-50 text-red-900' title={d.ingest_error || undefined}>
                        登録失敗
                      </ChipLabel>
                    )}
                    {d.pii_status === 'pending' && d.ingest_status === 'ready' && (
                      <ChipLabel className='bg-solid-gray-200 text-solid-gray-800'>
                        個人情報検査中
                      </ChipLabel>
                    )}
                    {d.pii_status === 'suspected' && (
                      <ChipLabel
                        className='bg-orange-50 text-orange-900'
                        title={
                          (d.pii_hits ?? [])
                            .slice(0, 5)
                            .map((h) => `${h.category}: ${h.context || h.match}`)
                            .join('\n') || (d.pii_labels ?? []).join('・') || undefined
                        }
                      >
                        個人情報: {(d.pii_labels ?? []).join('・') || '検知'}
                      </ChipLabel>
                    )}
                    <span className='font-bold'>{d.source}</span>
                  </span>
                  <span className='text-dns-14N-130 text-solid-gray-600'>
                    {d.page_count > 0 ? `${d.page_count} ページ・` : ''}
                    タグ: {(d.tags ?? []).length > 0 ? (d.tags ?? []).join(', ') : 'なし（検索対象外）'}
                    {d.ingest_status === 'failed' && d.ingest_error
                      ? `・${d.ingest_error}`
                      : ''}
                  </span>
                  {d.pii_status === 'suspected' && (d.pii_hits ?? []).length > 0 && (
                    <ul className='text-dns-14N-130 text-orange-900 list-disc pl-5'>
                      {(d.pii_hits ?? []).slice(0, 5).map((h, i) => (
                        <li key={`${h.category}-${h.offset ?? i}-${h.match}`}>
                          {h.category}: 「{h.context || h.match}」
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {canManage && (
                  <div className='flex shrink-0 gap-2'>
                    <Button
                      variant='text'
                      size='sm'
                      aria-disabled={busy || undefined}
                      onClick={() => (retagFor === d.source ? setRetagFor(null) : openRetag(d))}
                    >
                      タグ編集
                    </Button>
                    <Button
                      variant='text'
                      size='sm'
                      className='text-error-2'
                      aria-disabled={busy || undefined}
                      onClick={() => handleDelete(d.source)}
                    >
                      削除
                    </Button>
                  </div>
                )}
              </div>

              {canManage && retagFor === d.source && (
                <div className='flex flex-col gap-3 rounded-8 bg-solid-gray-50 p-4'>
                  <TagPicker
                    idPrefix={`retag-${d.doc_id}`}
                    tags={tags}
                    selected={retagSelected}
                    onToggle={(tag) =>
                      setRetagSelected((prev) =>
                        prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
                      )
                    }
                    newTagsText={retagNewText}
                    onNewTagsText={setRetagNewText}
                  />
                  <div className='flex gap-2'>
                    <Button
                      variant='solid-fill'
                      size='sm'
                      aria-disabled={busy || undefined}
                      onClick={() => handleRetagSave(d.source)}
                    >
                      保存
                    </Button>
                    <Button variant='text' size='sm' onClick={() => setRetagFor(null)}>
                      キャンセル
                    </Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <SupportText>
        ※ ファイルの個別再インデックスには非対応です。内容を更新する場合は同名で再登録してください（自動的に上書きされます）。
      </SupportText>
    </div>
  );
};
