import { useEffect, useMemo, useState } from 'react';
import { PageTitle } from '@/components/PageTitle';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { APP_TITLE } from '@/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { DocsSection } from './DocsSection';
import { RegisterSection } from './RegisterSection';
import { TagsSection } from './TagsSection';
import { useDocs, useScopes, useTags } from './useKnowledge';

type Tab = 'docs' | 'register' | 'tags';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'docs', label: 'ドキュメント管理' },
  { id: 'register', label: 'ドキュメント登録' },
  { id: 'tags', label: 'タグ管理' },
];

export const KnowledgePage = () => {
  const { scopes, isSystemAdmin, isLoading: scopesLoading } = useScopes();
  const [scope, setScope] = useState('');
  const [tab, setTab] = useState<Tab>('docs');

  // スコープ一覧の初期化: 先頭（共有ナレッジ）を既定選択
  useEffect(() => {
    if (!scope && scopes.length > 0) {
      setScope(scopes[0].scope);
    }
  }, [scope, scopes]);

  const current = useMemo(() => scopes.find((s) => s.scope === scope), [scopes, scope]);
  const canManage = current?.canManage ?? false;

  const { tags, mutate: mutateTags } = useTags(scope || undefined);
  const { docs, mutate: mutateDocs } = useDocs(scope || undefined);

  return (
    <LayoutBody>
      <PageTitle title={`ナレッジ管理${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div className='mx-auto p-6 max-w-(--page-width) lg:p-8'>
        <BreadcrumbsNav
          items={[{ label: 'ホーム', to: '/' }, { label: 'ナレッジ管理' }]}
          className='mb-4'
        />
        <h1 className='mb-2 text-std-20B-160 lg:text-std-24B-150'>ナレッジ管理</h1>
        <p className='mb-6 text-solid-gray-600'>
          共有ナレッジや所属チームの資料を登録・管理します。検索は「AIアプリ」のナレッジ検索から行えます。
        </p>

        {/* スコープセレクタ */}
        <div className='mb-6 flex flex-col gap-1.5'>
          <Label htmlFor='knowledge-scope' size='md'>
            対象スコープ
          </Label>
          <Select
            id='knowledge-scope'
            blockSize='md'
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className='max-w-md'
            aria-disabled={scopesLoading || scopes.length === 0 || undefined}
          >
            {scopes.length === 0 && <option value=''>読み込み中…</option>}
            {scopes.map((s) => (
              <option key={s.scope} value={s.scope}>
                {s.name}
                {s.kind === 'common' ? '' : '（チーム）'}
              </option>
            ))}
          </Select>
          {current && !canManage && (
            <p className='text-dns-14N-130 text-solid-gray-600'>
              {current.kind === 'common'
                ? 'このスコープは閲覧のみ可能です（共有ナレッジの管理はシステム管理者に限られます）。'
                : 'このスコープは閲覧のみです。配下チームの資料は親所属から見られますが、登録・削除は明示メンバーだけが行えます。'}
            </p>
          )}
        </div>

        {/* タブ */}
        <div className='mb-6 flex flex-wrap gap-2 border-b border-solid-gray-300'>
          {TABS.map((t) => (
            <button
              key={t.id}
              type='button'
              onClick={() => setTab(t.id)}
              className={`-mb-px border-b-2 px-4 py-2 text-oln-16B-100 ${
                tab === t.id
                  ? 'border-blue-900 text-blue-900'
                  : 'border-transparent text-solid-gray-600 hover:text-solid-gray-900'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {!scope ? (
          <p className='text-solid-gray-600'>スコープを選択してください。</p>
        ) : (
          <>
            {tab === 'docs' && (
              <DocsSection
                scope={scope}
                canManage={canManage}
                isSystemAdmin={isSystemAdmin}
                tags={tags}
                docs={docs}
                mutateDocs={mutateDocs}
                mutateTags={mutateTags}
              />
            )}
            {tab === 'register' &&
              (canManage ? (
                <RegisterSection
                  scope={scope}
                  tags={tags}
                  mutateTags={mutateTags}
                  mutateDocs={mutateDocs}
                />
              ) : (
                <p className='text-solid-gray-600'>
                  このスコープへの登録権限がありません。
                </p>
              ))}
            {tab === 'tags' && (
              <TagsSection
                scope={scope}
                canManage={canManage}
                tags={tags}
                mutateTags={mutateTags}
              />
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};
