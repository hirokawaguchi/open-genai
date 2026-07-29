import { useEffect } from 'react';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { APP_TITLE } from '@/constants';
import { clearToken, login } from '@/local/localAuth';

export const AuthErrorPage = () => {
  const PAGE_TITLE = '認証エラー';

  // 壊れたセッションを残さないよう、到達時に古いトークンを破棄する
  useEffect(() => {
    clearToken();
  }, []);

  return (
    <>
      <PageTitle title={`${PAGE_TITLE}${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div className='m-8'>
        <main id='mainContents' className='flex flex-col gap-4'>
          <h1 className='mb-8 text-std-28B-150 lg:text-std-45B-140'>認証エラー</h1>

          <p className='text-std-18N-160'>
            認証に失敗しました。下のボタンから再度ログインしてください。解消しない場合は管理者にお問い合わせください。
          </p>

          <div>
            <Button size='lg' variant='solid-fill' onClick={() => login()}>
              ログイン画面へ戻る
            </Button>
          </div>
        </main>
      </div>
    </>
  );
};
