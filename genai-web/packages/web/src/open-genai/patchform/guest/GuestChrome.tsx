import type { ReactNode } from 'react';
import { APP_TITLE } from '@/constants';
import { usePatchformApi } from '../PatchformApiContext';
import { GuestLogin } from './GuestLogin';
import { GuestNarrow } from './GuestNarrow';
import { clearSession, readSession } from './guestSession';

// 庁内の実ページ（DocmakerPage / PatchformApplicationPage / PatchformWizardPage）を
// 庁外でそのまま描画するための薄い外枠。セッションが無ければログイン画面を出し、
// あればページ本体はそのまま（庁内と同じ全幅レイアウト）に、上部に本人＋ログアウトの
// スリムバーだけを足す。ページ本体には一切手を入れない。
export const GuestChrome = ({ children }: { children: ReactNode }) => {
  const api = usePatchformApi();
  const session = readSession();

  if (!session) {
    return (
      <GuestNarrow>
        <GuestLogin />
      </GuestNarrow>
    );
  }

  const onLogout = () => {
    void api.post('/public/api/auth/logout').catch(() => undefined);
    clearSession();
    location.replace('/public/mine');
  };

  return (
    <div className='min-h-screen bg-white'>
      <header className='flex flex-wrap items-center justify-between gap-2 border-b border-solid-gray-300 bg-white px-6 py-2 lg:px-8'>
        <span className='text-dns-14N-130 text-solid-gray-600'>{APP_TITLE}・マイ手続き</span>
        <div className='flex items-center gap-3'>
          {session.email ? (
            <span className='text-dns-14N-130 text-solid-gray-600'>{session.email}</span>
          ) : null}
          <button
            type='button'
            className='text-dns-14N-130 text-blue-900 underline-offset-2 hover:underline'
            onClick={onLogout}
          >
            ログアウト
          </button>
        </div>
      </header>
      {children}
    </div>
  );
};
