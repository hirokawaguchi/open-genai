import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { usePatchformApi } from '../PatchformApiContext';
import { clearSession, readSession } from './guestSession';

// 匿名の共有リンク束（/public/p）向けの外枠。ログインは強制しない（capability URL）。
// ログイン済みなら email、未ログインなら「ログイン」導線だけを上部に出し、
// 本体（庁内と同一の実ページ）はフル幅で描画する。
export const GuestAnonChrome = ({ children }: { children: ReactNode }) => {
  const api = usePatchformApi();
  const session = readSession();
  // ログアウトしてから改めてログインし直す導線。email だけ残って操作が「セッションが不正」に
  // なる状態（例: サーバ再起動で署名鍵が変わった）からも、ここで抜け出せる。
  const onLogout = () => {
    void api.post('/public/api/auth/logout').catch(() => undefined);
    clearSession();
    location.reload();
  };
  return (
    <div className='min-h-screen bg-white'>
      <header className='flex flex-wrap items-center justify-between gap-2 border-b border-solid-gray-300 bg-white px-6 py-2 lg:px-8'>
        <span className='text-dns-14N-130 text-solid-gray-600'>Open GENAI・申請</span>
        <div className='flex items-center gap-3'>
          {session?.email ? (
            <>
              <span className='text-dns-14N-130 text-solid-gray-600'>{session.email}</span>
              <button
                type='button'
                className='text-dns-14N-130 text-blue-900 underline-offset-2 hover:underline'
                onClick={onLogout}
              >
                ログアウト
              </button>
            </>
          ) : (
            <Link
              to='/public/mine'
              className='text-dns-14N-130 text-blue-900 underline-offset-2 hover:underline'
            >
              マイ手続きにログイン
            </Link>
          )}
        </div>
      </header>
      {children}
    </div>
  );
};
