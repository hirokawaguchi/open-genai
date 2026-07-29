import { App } from './App.tsx';
import './index.css';
import React, { ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import { ErrorBoundary } from 'react-error-boundary';
import { BrowserRouter } from 'react-router';
import { OnlineStatusProvider } from '@/components/OnlineStatusProvider';
import { GlobalErrorFallback } from '@/components/ui/GlobalErrorFallback';
import { captureTokenFromUrl, clearToken, isAuthenticated, login } from '@/local/localAuth';

// ACS からのリダイレクトで付与された #token= を取り込む（描画前に実行）
captureTokenFromUrl();

// Open GENAI: ローカル SAML 認証のログインゲート。
// 未認証なら backend の SAML ログインへリダイレクトする。
// サインアウト後・認証エラーページは認証不要で表示する。
const AuthGate = ({ children }: { children: ReactNode }) => {
  const path = window.location.pathname;
  if (path === '/signed-out' || path === '/auth-error') {
    // 認証エラー到達時は壊れたトークンを残さない（セッションを永続化しない）
    if (path === '/auth-error') {
      clearToken();
    }
    return <>{children}</>;
  }
  if (!isAuthenticated()) {
    login();
    return null;
  }
  return <>{children}</>;
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <OnlineStatusProvider>
      <AuthGate>
        <BrowserRouter>
          <ErrorBoundary
            fallbackRender={GlobalErrorFallback}
            onReset={() => window.location.reload()}
          >
            <App />
          </ErrorBoundary>
        </BrowserRouter>
      </AuthGate>
    </OnlineStatusProvider>
  </React.StrictMode>,
);
