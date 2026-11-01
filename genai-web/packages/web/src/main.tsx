import { App } from './App.tsx';
import './index.css';
import React, { ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import { ErrorBoundary } from 'react-error-boundary';
import { BrowserRouter } from 'react-router';
import { OnlineStatusProvider } from '@/components/OnlineStatusProvider';
import { GlobalErrorFallback } from '@/components/ui/GlobalErrorFallback';
import {
  captureTokenFromUrl,
  clearToken,
  getToken,
  isAuthenticated,
  login,
  refreshSession,
  startSessionKeepAlive,
} from '@/local/localAuth';

// ACS からのリダイレクトで付与された #token= を取り込む（描画前に実行）
captureTokenFromUrl();

// Open GENAI: ローカル SAML 認証のログインゲート。
// 未認証なら backend の SAML ログインへリダイレクトする。
// サインアウト後・認証エラーページは認証不要で表示する。
const AuthGate = ({ children }: { children: ReactNode }) => {
  const path = window.location.pathname;
  const publicPath = path === '/signed-out' || path === '/auth-error';
  const [ready, setReady] = React.useState(() => publicPath || isAuthenticated());

  React.useEffect(() => {
    if (publicPath) {
      // 認証エラー到達時は壊れたトークンを残さない（セッションを永続化しない）
      if (path === '/auth-error') {
        clearToken();
      }
      return;
    }
    if (isAuthenticated()) {
      setReady(true);
      return;
    }
    // JWT の期限が切れていても、次のリセット時刻（既定は午前4時）までは延長して入る。
    if (!getToken()) {
      login();
      return;
    }
    let cancelled = false;
    void refreshSession().then((ok) => {
      if (cancelled) {
        return;
      }
      if (ok) {
        setReady(true);
        return;
      }
      login();
    });
    return () => {
      cancelled = true;
    };
  }, [path, publicPath]);

  if (publicPath) {
    return <>{children}</>;
  }
  if (!ready) {
    return (
      <div
        style={{
          minHeight: '100dvh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#333',
          fontFamily: 'sans-serif',
        }}
      >
        ログインを確認しています…
      </div>
    );
  }
  // 認証済みの間は、期限前にサイレント再発行してセッションを維持する
  startSessionKeepAlive();
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
