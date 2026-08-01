import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Textarea } from '@/components/ui/dads/Textarea';
import { TemplateKindChip } from './TemplateKindChip';
import { missingVariables, substitute } from './templateVars';
import type { PromptTemplate } from './types';

type Props = {
  templates: PromptTemplate[];
};

/** 「使う」: テンプレ一覧から選び、変数を入れてチャットへ流し込む。 */
export const PromptUseSection = ({ templates }: Props) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [variables, setVariables] = useState<Record<string, string>>({});

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return templates;
    }
    return templates.filter(
      (t) => t.title.toLowerCase().includes(q) || t.body.toLowerCase().includes(q),
    );
  }, [templates, query]);

  const selected = useMemo(
    () => templates.find((t) => t.id === selectedId) ?? null,
    [templates, selectedId],
  );

  const onSelect = (t: PromptTemplate) => {
    setSelectedId(t.id);
    setVariables({});
  };

  const preview = selected ? substitute(selected.body, variables) : '';
  const missing = selected ? missingVariables(selected.body, variables) : [];

  const openInChat = () => {
    if (!selected) {
      return;
    }
    const filled = substitute(selected.body, variables);
    const state =
      selected.target === 'system'
        ? { systemContext: filled, autoSubmit: false }
        : { content: filled, autoSubmit: false };
    navigate('/chat', { state });
  };

  return (
    <div className='grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]'>
      <div className='flex flex-col gap-3'>
        <Label htmlFor='prompt-search' size='sm'>
          テンプレートを探す
        </Label>
        <Input
          id='prompt-search'
          blockSize='md'
          placeholder='タイトル・本文で検索'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {filtered.length === 0 ? (
          <SupportText className='mt-2'>該当するテンプレートがありません。</SupportText>
        ) : (
          <ul className='flex max-h-[60vh] flex-col gap-2 overflow-y-auto pr-1'>
            {filtered.map((t) => {
              const isActive = t.id === selectedId;
              return (
                <li key={t.id}>
                  <button
                    type='button'
                    onClick={() => onSelect(t)}
                    aria-pressed={isActive}
                    className={`flex w-full flex-col gap-1 rounded-8 border px-4 py-3 text-left transition-colors hover:border-blue-900 hover:bg-blue-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-black ${
                      isActive
                        ? 'border-blue-900 bg-blue-50'
                        : 'border-solid-gray-300 bg-white'
                    }`}
                  >
                    <span className='flex items-center gap-2'>
                      <TemplateKindChip kind={t.kind} />
                      <span className='text-std-16B-150 text-solid-gray-900'>{t.title}</span>
                    </span>
                    <span className='line-clamp-2 text-dns-14N-130 text-solid-gray-600'>
                      {t.body}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className='flex flex-col gap-4'>
        {!selected ? (
          <div className='flex min-h-[200px] items-center justify-center rounded-8 border border-dashed border-solid-gray-300 bg-solid-gray-50 p-6 text-center'>
            <SupportText>左の一覧からテンプレートを選ぶと、ここで内容を編集できます。</SupportText>
          </div>
        ) : (
          <>
            <div className='flex items-center gap-2'>
              <TemplateKindChip kind={selected.kind} />
              <h2 className='text-std-20B-160 text-solid-gray-900'>{selected.title}</h2>
            </div>

            {selected.variables.length > 0 && (
              <div className='flex flex-col gap-4'>
                <p className='text-std-16B-170 text-solid-gray-800'>変数を入力</p>
                {selected.variables.map((name) => (
                  <div key={name} className='flex flex-col gap-1.5'>
                    <Label htmlFor={`var-${name}`} size='sm'>
                      {name}
                    </Label>
                    <Textarea
                      id={`var-${name}`}
                      rows={2}
                      value={variables[name] ?? ''}
                      onChange={(e) =>
                        setVariables((prev) => ({ ...prev, [name]: e.target.value }))
                      }
                    />
                  </div>
                ))}
              </div>
            )}

            <div className='flex flex-col gap-1.5'>
              <p className='text-std-16B-170 text-solid-gray-800'>組み上がるプロンプト</p>
              <pre className='max-h-80 overflow-auto rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-4 py-3 text-dns-14N-130 leading-relaxed whitespace-pre-wrap'>
                {preview || '（プレビューする内容がありません）'}
              </pre>
              {missing.length > 0 && (
                <SupportText>
                  未入力の変数: {missing.map((m) => `{{${m}}}`).join(', ')}
                </SupportText>
              )}
            </div>

            <div className='flex flex-wrap items-center gap-3'>
              <Button type='button' variant='solid-fill' size='md' onClick={openInChat}>
                {selected.target === 'system'
                  ? 'システムプロンプトに設定してチャットへ'
                  : 'チャットで開く'}
              </Button>
              <SupportText>
                {selected.target === 'system'
                  ? 'チャットのシステムプロンプトに設定されます。'
                  : 'チャットの入力欄に本文が入ります（送信前に編集できます）。'}
              </SupportText>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
