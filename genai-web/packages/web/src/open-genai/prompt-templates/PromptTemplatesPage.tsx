import { useState } from 'react';
import { PiBookOpenBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PromptCreateSection } from './PromptCreateSection';
import { PromptManageSection } from './PromptManageSection';
import { PromptUseSection } from './PromptUseSection';
import { usePromptTemplates, usePromptTemplateActions } from './usePromptTemplates';

type Mode = 'use' | 'create' | 'manage';

const MODES: { id: Mode; label: string }[] = [
  { id: 'use', label: '使う' },
  { id: 'create', label: '作成' },
  { id: 'manage', label: '管理' },
];

/**
 * プロンプトテンプレート専用ページ（OpenGENAI 拡張）。
 * 源内の汎用 exApp フォームでは操作が縦並びで直感的でないため、一覧→変数→
 * プレビュー→チャットへ、というカタログ型 UI を専用ページとして提供する。
 */
export const PromptTemplatesPage = () => {
  const [mode, setMode] = useState<Mode>('use');
  const { templates, teams, canCreateStandard, isLoading, loadError, mutate } =
    usePromptTemplates();
  const { create, remove, submitting, error, setError } = usePromptTemplateActions(mutate);

  const switchMode = (next: Mode) => {
    setError(null);
    setMode(next);
  };

  return (
    <LayoutBody>
      <PageTitle title='プロンプトテンプレート' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <div className='flex flex-col gap-4'>
          <BreadcrumbsNav
            items={[
              { label: 'ホーム', to: '/' },
              { label: 'AIアプリ', to: '/apps' },
              { label: 'プロンプトテンプレート' },
            ]}
          />
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>プロンプトテンプレート</h1>
          <p className='text-std-16N-170 text-solid-gray-700'>
            標準テンプレートの利用や、個人／チーム共有テンプレートの作成ができます。選ぶとそのままチャットへ流し込めます。
          </p>
          <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
            <DisclosureSummary>
              <span className='flex items-center text-std-16B-150'>
                <PiBookOpenBold className='mr-2 size-5 flex-none' />
                使い方（クリックで開閉）
              </span>
            </DisclosureSummary>
            <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
              <p>・「使う」でテンプレートを選び、本文の {'{{変数}}'} に値を入れるとプレビューに反映されます。</p>
              <p>・「チャットで開く」で、組み上がった文面がチャットに入ります（送信前に編集できます）。</p>
              <p>・「作成」で個人／チーム共有／全体公開のテンプレートを追加できます（標準は管理者のみ）。</p>
              <p>・「管理」で自分が作成したテンプレートを削除できます。</p>
            </div>
          </Disclosure>
        </div>

        <div role='tablist' aria-label='操作' className='flex gap-1 border-b border-solid-gray-300'>
          {MODES.map((m) => {
            const isActive = m.id === mode;
            return (
              <button
                key={m.id}
                type='button'
                role='tab'
                aria-selected={isActive}
                onClick={() => switchMode(m.id)}
                className={`-mb-px border-b-2 px-4 py-2 text-oln-16B-100 transition-colors focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-black ${
                  isActive
                    ? 'border-blue-900 text-blue-900'
                    : 'border-transparent text-solid-gray-600 hover:text-solid-gray-900'
                }`}
              >
                {m.label}
              </button>
            );
          })}
        </div>

        {isLoading ? (
          <p className='text-std-16N-170 text-solid-gray-600'>読み込み中...</p>
        ) : loadError ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            {loadError}
          </p>
        ) : (
          <>
            {mode === 'use' && <PromptUseSection templates={templates} />}
            {mode === 'create' && (
              <PromptCreateSection
                teams={teams}
                canCreateStandard={canCreateStandard}
                submitting={submitting}
                error={error}
                onSubmit={async (input) => {
                  const created = await create(input);
                  return created !== null;
                }}
              />
            )}
            {mode === 'manage' && (
              <PromptManageSection
                templates={templates}
                submitting={submitting}
                error={error}
                onDelete={remove}
              />
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};
