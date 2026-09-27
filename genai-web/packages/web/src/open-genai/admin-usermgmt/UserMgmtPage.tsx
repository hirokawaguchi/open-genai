import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { ADMIN_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { USERMGMT_EXAPP_ID } from '@/layout/navItems';
import { PageTitle } from '@/components/PageTitle';
import { useMyTenants } from '@/open-genai/tenants/useTenants';
import { UserCreateSection } from './UserCreateSection';
import { UserCsvSection } from './UserCsvSection';
import { UserEditDialog } from './UserEditDialog';
import type { ManagedUser } from './types';
import { useUsers } from './useUserMgmt';

type Mode = 'list' | 'create' | 'csv';

const MODES: { id: Mode; label: string }[] = [
  { id: 'list', label: '利用者一覧' },
  { id: 'create', label: '利用者登録' },
  { id: 'csv', label: 'CSV一括処理' },
];

const LIMIT_OPTIONS = [50, 100, 200, 500, 1000];
const NO_TENANT_MESSAGE = '所属する棟がありません。管理者に連絡してください。';

/**
 * 利用者一括管理 専用ページ（管理者限定・OpenGENAI 拡張）。
 * 源内の汎用 exApp フォーム（操作 select ＋ Markdown 出力）では一覧・ドライラン・適用の
 * 往復がしづらいため、一覧と CSV 一括処理を専用ページとして提供する。
 */
export const UserMgmtPage = () => {
  const { tenants, activeTenantId, isSystemAdmin, isLoading } = useMyTenants();
  const [mode, setMode] = useState<Mode>('list');
  const active = tenants.find((t) => t.tenantId === activeTenantId);
  const activeOrg = active && active.kind !== 'shared' ? active : undefined;
  const canManage = !!activeOrg && (isSystemAdmin || !!activeOrg.isAdmin);

  const header = (
    <ManagedAppHeader
      teamId={ADMIN_EXAPPS_TEAM_ID}
      exAppId={USERMGMT_EXAPP_ID}
      fallbackTitle='利用者一括管理'
      fallbackDescription='利用者の一覧、登録、変更、および CSV による一括処理ができます。'
      fallbackHowTo={
        <>
          <p>1. 人はメールアドレスで一人です。ログイン名は入り方、氏名は表示名です。</p>
          <p>2. メールアドレスとログイン名は、登録後は変えません。アドレスを変えるときは、新しい人として登録します。</p>
          <p>3. 所属は、主所属が一つで、ほかの棟は招待です。管理者にするかどうかは、棟ごとに付けます。</p>
          <p>4. 変更できるのは、氏名、権限、有効か無効か、パスワードです。いま開いている棟の所属者だけを、この画面で扱います。</p>
          <p>・「利用者一覧」で検索し、行の「変更」から氏名・権限・有効状態・パスワードを更新できます。</p>
          <p>・「利用者登録」ではユーザー名、メールアドレス、姓が必須です。名は空でも登録できます。</p>
          <p>・「CSV一括処理」では、まず「ドライラン」で内容を確認します。既存の人の行でメールアドレスが違うとその行は拒否されます。</p>
          <p>・問題なければ「適用」で反映します（作成・更新・削除。削除は元に戻せません）。</p>
          <p>・password 列を含む CSV の保管・共有には十分注意してください。</p>
        </>
      }
    />
  );

  if (isLoading) {
    return (
      <LayoutBody>
        <PageTitle title='利用者一括管理' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          {header}
          <SupportText>読み込み中...</SupportText>
        </div>
      </LayoutBody>
    );
  }

  if (!canManage) {
    return (
      <LayoutBody>
        <PageTitle title='利用者一括管理' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          {header}
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            {activeOrg ? 'このページの閲覧には管理者権限が必要です。' : NO_TENANT_MESSAGE}
          </p>
        </div>
      </LayoutBody>
    );
  }

  return (
    <LayoutBody>
      <PageTitle title='利用者一括管理' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        {header}

        <div role='tablist' aria-label='操作' className='flex gap-1 border-b border-solid-gray-300'>
          {MODES.map((m) => {
            const isActive = m.id === mode;
            return (
              <button
                key={m.id}
                type='button'
                role='tab'
                aria-selected={isActive}
                onClick={() => setMode(m.id)}
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

        {mode === 'list' ? (
          <UserListSection isSystemAdmin={isSystemAdmin} />
        ) : mode === 'create' ? (
          <UserCreateSection isSystemAdmin={isSystemAdmin} onCreated={() => setMode('list')} />
        ) : (
          <UserCsvSection onApplied={() => setMode('list')} />
        )}
      </div>
    </LayoutBody>
  );
};

/** 「利用者一覧」: いま開いている組織の主所属だけを表示し、行から変更できる。 */
const UserListSection = ({ isSystemAdmin }: { isSystemAdmin: boolean }) => {
  const [draftSearch, setDraftSearch] = useState('');
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(200);
  const [editing, setEditing] = useState<ManagedUser | null>(null);

  const { users, count, limitReached, isLoading, forbidden, forbiddenMessage, loadError, mutate } =
    useUsers(search, limit);

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-end gap-3'>
        <div className='flex min-w-60 flex-1 flex-col gap-1.5'>
          <Label htmlFor='user-search' size='sm'>
            検索（username / email / 氏名の部分一致）
          </Label>
          <Input
            id='user-search'
            blockSize='md'
            value={draftSearch}
            onChange={(e) => setDraftSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                setSearch(draftSearch);
              }
            }}
          />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='user-limit' size='sm'>
            表示件数
          </Label>
          <Select
            id='user-limit'
            blockSize='md'
            value={String(limit)}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}件
              </option>
            ))}
          </Select>
        </div>
        <Button type='button' variant='solid-fill' size='md' onClick={() => setSearch(draftSearch)}>
          検索
        </Button>
        <Button type='button' variant='outline' size='md' onClick={() => mutate()}>
          再読み込み
        </Button>
      </div>

      {forbidden ? (
        <p className='text-dns-16N-130 text-error-1' role='alert'>
          {forbiddenMessage}
        </p>
      ) : loadError ? (
        <p className='text-dns-16N-130 text-error-1' role='alert'>
          {loadError}
        </p>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <SupportText>
              {count === 0
                ? '該当する利用者はいません。'
                : `${count} 件を表示${limitReached ? '（上限に達しています）' : ''}`}
            </SupportText>
            {isLoading && <SupportText>読み込み中...</SupportText>}
          </div>

          {users.length > 0 && (
            <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
              <table className='w-full border-collapse text-left text-dns-14N-130'>
                <thead className='bg-solid-gray-50 text-solid-gray-700'>
                  <tr>
                    <th className='px-3 py-2 font-bold'>username</th>
                    <th className='px-3 py-2 font-bold'>email</th>
                    <th className='px-3 py-2 font-bold'>氏名</th>
                    <th className='px-3 py-2 font-bold'>groups</th>
                    <th className='whitespace-nowrap px-3 py-2 font-bold'>状態</th>
                    <th className='whitespace-nowrap px-3 py-2 font-bold'>操作</th>
                  </tr>
                </thead>
                <tbody className='divide-y divide-solid-gray-300'>
                  {users.map((u) => {
                    const locked = !isSystemAdmin && u.groups.includes('SystemAdminGroup');
                    return (
                      <tr key={u.id || u.username} className='align-top text-solid-gray-900'>
                        <td className='px-3 py-2'>{u.username || '-'}</td>
                        <td className='px-3 py-2'>{u.email || '-'}</td>
                        <td className='px-3 py-2'>{u.name || '-'}</td>
                        <td className='px-3 py-2'>
                          {u.groups.length > 0 ? u.groups.join(', ') : '-'}
                        </td>
                        <td className='whitespace-nowrap px-3 py-2'>
                          {u.enabled ? (
                            '有効'
                          ) : (
                            <span className='text-solid-gray-500'>無効</span>
                          )}
                        </td>
                        <td className='whitespace-nowrap px-3 py-2'>
                          {locked ? (
                            <span className='text-solid-gray-500'>変更できません</span>
                          ) : (
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              onClick={() => setEditing(u)}
                            >
                              変更
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {editing && (
        <UserEditDialog
          user={editing}
          isSystemAdmin={isSystemAdmin}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            mutate();
          }}
        />
      )}
    </div>
  );
};
