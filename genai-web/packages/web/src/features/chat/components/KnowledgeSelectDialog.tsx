import { useMemo } from 'react';
import { tagFileChoices } from '@/open-genai/knowledge/tagFileCounts';
import { useDocs, useScopes, useTags } from '@/open-genai/knowledge/useKnowledge';
import type { KnowledgeScope, KnowledgeTag } from '@/open-genai/knowledge/types';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import type { KnowledgePick } from '@/features/chat/stores/useChatStore';

type Props = {
  isOpen: boolean;
  picks: KnowledgePick[];
  onChange: (picks: KnowledgePick[]) => void;
  onClose: () => void;
  /** 未指定なら、チャットの「選んだタグで検索する」説明を出す。 */
  description?: string;
  /** MCP の共有ナレッジが On のとき、共通スコープはすべて対象として見せ、個別のチェックは出さない。 */
  sharedKnowledgeLocked?: boolean;
};

const pickKey = (scope: string, tag: string) => `${scope}\u0000${tag}`;

const ScopeTags = ({
  scope,
  selected,
  locked,
  onToggle,
}: {
  scope: KnowledgeScope;
  selected: Set<string>;
  locked: boolean;
  onToggle: (tag: KnowledgeTag, checked: boolean) => void;
}) => {
  const { tags, isLoading, error } = useTags(scope.scope);
  const { docs, isLoading: docsLoading, error: docsError } = useDocs(scope.scope);
  const fileCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const choice of tagFileChoices(docs)) {
      counts.set(choice.tag, choice.files);
    }
    return counts;
  }, [docs]);
  const searchable = tags.filter((tag) => tag.chunks > 0);

  return (
    <section className='space-y-2'>
      <h3 className='text-std-16B-170'>{scope.name}</h3>
      {locked && (
        <p className='text-dns-14N-130 text-solid-gray-700'>
          MCP の共有ナレッジが On です。共通チームの文書はすべて対象です。一部だけにするには、MCP を Off にしてからタグを登録してください。
        </p>
      )}
      {isLoading && <p className='text-solid-gray-600'>タグを読み込んでいます。</p>}
      {error && <p className='text-error-1'>タグを読み込めませんでした。</p>}
      {!isLoading && !error && searchable.length === 0 && (
        <p className='text-solid-gray-600'>検索できるタグはありません。</p>
      )}
      {searchable.length > 0 && (
        <ul className='m-0 grid list-none gap-2 p-0 sm:grid-cols-2'>
          {searchable.map((tag) => {
            const count = !docsLoading && !docsError ? `（${fileCounts.get(tag.tag) ?? 0}件）` : '';
            if (locked) {
              return (
                <li key={tag.tag} className='text-solid-gray-800'>
                  {tag.tag}
                  {count}
                  <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>選択済み</span>
                </li>
              );
            }
            const id = `knowledge-tag-${scope.scope}-${tag.tag}`;
            const checked = selected.has(pickKey(scope.scope, tag.tag));
            return (
              <li key={tag.tag}>
                <label htmlFor={id} className='flex cursor-pointer items-start gap-2'>
                  <input
                    id={id}
                    type='checkbox'
                    className='mt-1'
                    checked={checked}
                    onChange={(event) => onToggle(tag, event.target.checked)}
                  />
                  <span>
                    {tag.tag}
                    {count}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};

/** 参照できるナレッジのタグを選び、閉じたあとも選択を残す。 */
export const KnowledgeSelectDialog = ({
  isOpen,
  picks,
  onChange,
  onClose,
  description,
  sharedKnowledgeLocked = false,
}: Props) => {
  const { scopes, isLoading, error } = useScopes();
  const selected = new Set(picks.map((pick) => pickKey(pick.scope, pick.tag)));
  const clearable = sharedKnowledgeLocked
    ? picks.filter((pick) => scopes.find((scope) => scope.scope === pick.scope)?.kind !== 'common')
    : picks;

  const toggle = (scope: KnowledgeScope, tag: KnowledgeTag, checked: boolean) => {
    if (checked) {
      if (selected.has(pickKey(scope.scope, tag.tag))) {
        return;
      }
      onChange([...picks, { scope: scope.scope, scopeName: scope.name, tag: tag.tag }]);
      return;
    }
    onChange(picks.filter((pick) => pick.scope !== scope.scope || pick.tag !== tag.tag));
  };

  return (
    <CustomDialog isOpen={isOpen} onClose={onClose}>
      <CustomDialogPanel>
        <CustomDialogHeader hasClose onClose={onClose}>
          ナレッジ選択
        </CustomDialogHeader>
        <CustomDialogBody>
          <p className='text-solid-gray-700'>
            {description ??
              'タグを選ぶと、そのタグが付いた文書を検索してから答えます。選んだタグは、解除するまで次の送信にも使います。'}
          </p>
          <div className='mt-4 max-h-[50vh] space-y-6 overflow-y-auto pr-1'>
            {isLoading && <p>参照できるナレッジを確認しています。</p>}
            {error && <p className='text-error-1'>ナレッジを読み込めませんでした。</p>}
            {!isLoading && !error && scopes.length === 0 && <p>参照できるナレッジはありません。</p>}
            {isOpen &&
              scopes.map((scope) => (
                <ScopeTags
                  key={scope.scope}
                  scope={scope}
                  selected={selected}
                  locked={sharedKnowledgeLocked && scope.kind === 'common'}
                  onToggle={(tag, checked) => toggle(scope, tag, checked)}
                />
              ))}
          </div>
          <div className='mt-6 flex justify-end gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={clearable.length === 0 || undefined}
              disabled={clearable.length === 0}
              onClick={() => onChange(picks.filter((pick) => !clearable.includes(pick)))}
            >
              すべて解除
            </Button>
            <Button type='button' variant='solid-fill' size='md' onClick={onClose}>
              閉じる
            </Button>
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
