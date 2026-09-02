import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { ADMIN_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useTeamAuth } from '@/features/teams/hooks/useTeamAuth';
import { LayoutBody } from '@/layout/LayoutBody';
import { USERMGMT_EXAPP_ID } from '@/layout/navItems';
import { PageTitle } from '@/components/PageTitle';
import { UserCsvSection } from './UserCsvSection';
import { useUsers } from './useUserMgmt';

type Mode = 'list' | 'csv';

const MODES: { id: Mode; label: string }[] = [
  { id: 'list', label: '利用者一覧' },
  { id: 'csv', label: 'CSV一括処理' },
];

const LIMIT_OPTIONS = [50, 100, 200, 500, 1000];

/**
 * 利用者一括管理 専用ページ（管理者限定・OpenGENAI 拡張）。
 * 源内の汎用 exApp フォーム（操作 select ＋ Markdown 出力）では一覧・ドライラン・適用の
 * 往復がしづらいため、一覧と CSV 一括処理を専用ページとして提供する。
 */
export const UserMgmtPage = () => {
  const { isSystemAdminGroup } = useTeamAuth();
  const [mode, setMode] = useState<Mode>('list');

  const header = (
    <ManagedAppHeader
      teamId={ADMIN_EXAPPS_TEAM_ID}
      exAppId={USERMGMT_EXAPP_ID}
      fallbackTitle='利用者一括管理'
      fallbackDescription='利用者アカウント（Keycloak）の一覧表示と、CSV による一括登録・更新・削除ができます（システム管理者のみ）。'
      fallbackHowTo={
        <>
          <p>・「利用者一覧」で現在のアカウントを検索・確認できます（変更はされません）。</p>
          <p>・「CSV一括処理」でCSVを貼り付け／読み込み、まず「ドライラン」で内容を確認します。</p>
          <p>・問題なければ「適用」で Keycloak に反映します（作成・更新・削除。削除は元に戻せません）。</p>
          <p>・password 列を含む CSV の保管・共有には十分注意してください。</p>
        </>
      }
    />
  );

  if (!isSystemAdminGroup) {
    return (
      <LayoutBody>
        <PageTitle title='利用者一括管理' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          {header}
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には管理者権限が必要です。
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

        {mode === 'list' ? <UserListSection /> : <UserCsvSection onApplied={() => setMode('list')} />}
      </div>
    </LayoutBody>
  );
};

/** 「利用者一覧」: 検索・件数指定で Keycloak の利用者を表示（読み取り専用）。 */
const UserListSection = () => {
  const [draftSearch, setDraftSearch] = useState('');
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(200);

  const { users, count, limitReached, isLoading, forbidden, loadError, mutate } = useUsers(
    search,
    limit,
  );

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
          このページの閲覧には管理者権限が必要です。
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
                  </tr>
                </thead>
                <tbody className='divide-y divide-solid-gray-300'>
                  {users.map((u) => (
                    <tr key={u.id || u.username} className='align-top text-solid-gray-900'>
                      <td className='px-3 py-2'>{u.username || '-'}</td>
                      <td className='px-3 py-2'>{u.email || '-'}</td>
                      <td className='px-3 py-2'>{u.name || '-'}</td>
                      <td className='px-3 py-2'>{u.groups.length > 0 ? u.groups.join(', ') : '-'}</td>
                      <td className='whitespace-nowrap px-3 py-2'>
                        {u.enabled ? (
                          '有効'
                        ) : (
                          <span className='text-solid-gray-500'>無効</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
};
