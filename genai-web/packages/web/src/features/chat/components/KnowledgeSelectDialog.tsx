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
};

const pickKey = (scope: string, tag: string) => `${scope}\u0000${tag}`;

const ScopeTags = ({
  scope,
  selected,
  onToggle,
}: {
  scope: KnowledgeScope;
  selected: Set<string>;
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
      {isLoading && <p className='text-solid-gray-600'>タグを読み込んでいます。</p>}
      {error && <p className='text-error-1'>タグを読み込めませんでした。</p>}
      {!isLoading && !error && searchable.length === 0 && (
        <p className='text-solid-gray-600'>検索できるタグはありません。</p>
      )}
      {searchable.length > 0 && (
        <ul className='m-0 grid list-none gap-2 p-0 sm:grid-cols-2'>
          {searchable.map((tag) => {
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
                    {!docsLoading && !docsError && `（${fileCounts.get(tag.tag) ?? 0}件）`}
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
export const KnowledgeSelectDialog = ({ isOpen, picks, onChange, onClose }: Props) => {
  const { scopes, isLoading, error } = useScopes();
  const selected = new Set(picks.map((pick) => pickKey(pick.scope, pick.tag)));

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
            タグを選ぶと、そのタグが付いた文書を検索してから答えます。選んだタグは、解除するまで次の送信にも使います。
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
                  onToggle={(tag, checked) => toggle(scope, tag, checked)}
                />
              ))}
          </div>
          <div className='mt-6 flex justify-end gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={picks.length === 0 || undefined}
              disabled={picks.length === 0}
              onClick={() => onChange([])}
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
