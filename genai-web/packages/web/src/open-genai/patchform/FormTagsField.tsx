import { useState, type KeyboardEvent } from 'react';
import { Label } from '@/components/ui/dads/Label';
import { NAVIGATION_TAG } from './labels';

type Props = {
  id: string;
  value: string[];
  onChange: (tags: string[]) => void;
  suggestions?: string[];
  disabled?: boolean;
};

const MAX_LEN = 30;

export const FormTagsField = ({ id, value, onChange, suggestions = [], disabled }: Props) => {
  const [draft, setDraft] = useState('');
  const extras = [NAVIGATION_TAG, ...suggestions].filter(
    (tag, index, all) => !value.includes(tag) && all.indexOf(tag) === index,
  );

  const add = (raw: string) => {
    const tag = raw.trim();
    if (!tag || tag.length > MAX_LEN || value.includes(tag)) {
      setDraft('');
      return;
    }
    onChange([...value, tag]);
    setDraft('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      add(draft);
    }
  };

  return (
    <div>
      <Label htmlFor={id} size='sm'>
        タグ
      </Label>
      <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
        フォームを管理しやすいようにタグを付けることができます。「{NAVIGATION_TAG}」タグはナビゲーションフォームです。一連の手続きで複数の様式を作成する場合は、同じタグでグルーピングしておくと良いでしょう。
      </p>
      {value.length > 0 ? (
        <ul className='mt-2 flex flex-wrap gap-2'>
          {value.map((tag) => (
            <li key={tag}>
              <button
                type='button'
                className='rounded-4 border border-solid-gray-420 bg-white px-2 py-1 text-dns-14N-130 text-solid-gray-800'
                disabled={disabled}
                onClick={() => onChange(value.filter((item) => item !== tag))}
                aria-label={`${tag}を外す`}
              >
                {tag} ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className='mt-2 flex flex-wrap items-center gap-2'>
        <input
          id={id}
          className='w-full max-w-64 rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder='例: 転入'
        />
        <button
          type='button'
          className='rounded-4 border border-solid-gray-420 px-3 py-2 text-dns-16N-130 text-solid-gray-800'
          disabled={disabled || !draft.trim()}
          onClick={() => add(draft)}
        >
          追加
        </button>
      </div>
      {extras.length > 0 ? (
        <div className='mt-2 flex flex-wrap gap-2'>
          {extras.slice(0, 8).map((tag) => (
            <button
              key={tag}
              type='button'
              className='rounded-4 border border-dashed border-solid-gray-420 px-2 py-1 text-dns-14N-130 text-solid-gray-700'
              disabled={disabled}
              onClick={() => add(tag)}
            >
              {tag}を付ける
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
};

export const FormTagList = ({ tags }: { tags?: string[] | null }) => {
  if (!tags?.length) return null;
  return (
    <ul className='mt-1 flex flex-wrap gap-1'>
      {tags.map((tag) => (
        <li
          key={tag}
          className={`rounded-4 px-2 py-0.5 text-dns-14N-130 ${
            tag === NAVIGATION_TAG
              ? 'bg-blue-50 text-blue-900'
              : 'bg-solid-gray-50 text-solid-gray-700'
          }`}
        >
          {tag}
        </li>
      ))}
    </ul>
  );
};
