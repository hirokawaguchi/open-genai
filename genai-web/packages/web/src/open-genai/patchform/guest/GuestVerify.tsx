import { useEffect, useRef, useState } from 'react';
import { usePatchformApi } from '../PatchformApiContext';
import { writeSession } from './guestSession';

// マジックリンクの着地点。?token を検証して外部セッションを確立し、一覧へ遷移する。
export const GuestVerify = () => {
  const api = usePatchformApi();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;
    const token = new URLSearchParams(location.search).get('token') || '';
    if (!token) {
      setError('リンクが不正です。');
      return;
    }
    void (async () => {
      try {
        const res = await api.post<{ token: string; email: string }>('/public/api/auth/verify', {
          token,
        });
        writeSession({ token: res.data.token, email: res.data.email });
        location.replace('/public/mine');
      } catch (e) {
        setError(
          e instanceof Error ? e.message : 'ログインに失敗しました。リンクが無効か期限切れです。',
        );
      }
    })();
  }, [api]);

  return (
    <div>
      {error ? (
        <>
          <h1 className='text-std-20B-160'>ログインできませんでした</h1>
          <p className='mt-3 text-error-1' role='alert'>
            {error}
          </p>
          <p className='mt-4'>
            <a href='/public/mine' className='text-blue-900 underline-offset-2 hover:underline'>
              ログイン画面に戻る
            </a>
          </p>
        </>
      ) : (
        <p className='hint text-solid-gray-700'>ログイン処理中...</p>
      )}
    </div>
  );
};
