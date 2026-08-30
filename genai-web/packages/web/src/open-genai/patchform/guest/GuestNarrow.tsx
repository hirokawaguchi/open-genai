import type { ReactNode } from 'react';

// 公開フォーム／共有リンク／ログインなど、庁内ページを使わない画面向けの
// 狭幅ラッパ（旧 form.html の .pf-guest-wrap 相当をReact側に持たせる）。
export const GuestNarrow = ({ children }: { children: ReactNode }) => (
  <div className='pf-guest-wrap'>
    <div className='pf-guest-brand'>Open GENAI</div>
    {children}
  </div>
);
