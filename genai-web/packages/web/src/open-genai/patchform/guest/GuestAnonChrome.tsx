import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { readSession } from './guestSession';

// 匿名の共有リンク束（/public/p）向けの外枠。ログインは強制しない（capability URL）。
// ログイン済みなら email、未ログインなら「ログイン」導線だけを上部に出し、
// 本体（庁内と同一の実ページ）はフル幅で描画する。
export const GuestAnonChrome = ({ children }: { children: ReactNode }) => {
  const session = readSession();
  return (
    <div className='min-h-screen bg-white'>
      <header className='flex flex-wrap items-center justify-between gap-2 border-b border-solid-gray-300 bg-white px-6 py-2 lg:px-8'>
        <span className='text-dns-14N-130 text-solid-gray-600'>Open GENAI・申請</span>
        <div className='flex items-center gap-3'>
          {session?.email ? (
            <span className='text-dns-14N-130 text-solid-gray-600'>{session.email}</span>
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
