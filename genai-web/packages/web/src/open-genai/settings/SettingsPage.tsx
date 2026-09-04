import { PageTitle } from '@/components/PageTitle';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { LayoutBody } from '@/layout/LayoutBody';
import { PasswordForm } from './components/PasswordForm';
import { ProfileForm } from './components/ProfileForm';
import { useMyProfile } from './useMyProfile';

export const SettingsPage = () => {
  const { profile, error, isLoading, mutate } = useMyProfile();

  return (
    <LayoutBody>
      <PageTitle title='アカウント設定' />
      <div className='mx-auto flex w-full max-w-3xl flex-col gap-6 p-4 lg:p-6'>
        <div className='flex flex-col gap-1'>
          <h1 className='text-std-22B-150 text-solid-gray-900'>アカウント設定</h1>
          <p className='text-dns-16N-170 text-solid-gray-700'>
            表示名（姓名）とパスワードを変更できます。
          </p>
        </div>

        {isLoading && (
          <div className='py-6'>
            <ProgressIndicator label='設定を読み込み中...' />
          </div>
        )}

        {!isLoading && error && (
          <div className='rounded-8 border border-amber-300 bg-amber-50 px-4 py-3 text-dns-14N-130 text-solid-gray-800'>
            設定情報を取得できませんでした。時間をおいて再度お試しください。
          </div>
        )}

        {!isLoading && profile && (
          <>
            <section className='flex flex-col gap-4 rounded-8 border border-solid-gray-300 bg-white p-5'>
              <div className='flex flex-col gap-1'>
                <h2 className='text-std-18B-160 text-solid-gray-900'>プロフィール</h2>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  ログインID: <span className='font-bold'>{profile.username}</span>
                  {profile.email ? `（${profile.email}）` : ''}
                </p>
              </div>
              <ProfileForm
                profile={profile}
                onUpdated={(next) => {
                  void mutate(next, { revalidate: false });
                }}
              />
            </section>

            <section className='flex flex-col gap-4 rounded-8 border border-solid-gray-300 bg-white p-5'>
              <div className='flex flex-col gap-1'>
                <h2 className='text-std-18B-160 text-solid-gray-900'>パスワード変更</h2>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  現在のパスワードを確認のうえ、新しいパスワードに変更します。
                </p>
              </div>
              <PasswordForm />
            </section>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
