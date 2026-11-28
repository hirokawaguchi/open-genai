import RFB from '@novnc/novnc';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, teamApi } from '@/lib/fetcher';
import { getIdToken } from '@/local/localAuth';
import { releaseBrowserMic } from './browserMic';
import { splitControlSocket } from './browserSocket';
import { browserWsUrl } from './browserWsUrl';
import { createHttpBrowserSocket, type HttpBrowserSocket } from './httpBrowserSocket';
import type { BrowserSessionInfo } from './types';

type ScreenSocket = WebSocket | HttpBrowserSocket;

const SOCKET_OPEN_MS = 4000;

/** サーバ上の Chromium へ接続し、画面の要素へ noVNC を載せる。 */
export const useBrowserSession = (autoStart: boolean) => {
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const screenRef = useRef<HTMLDivElement | null>(null);
  const socketRef = useRef<ScreenSocket | null>(null);
  const rfbRef = useRef<RFB | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const closingRef = useRef(false);
  const lastTouchRef = useRef(0);
  const runRef = useRef(0);

  const touch = useCallback(() => {
    const id = sessionIdRef.current;
    if (!id) {
      return;
    }
    const now = Date.now();
    if (now - lastTouchRef.current < 10_000) {
      return;
    }
    lastTouchRef.current = now;
    void teamApi
      .post(`browser/sessions/${encodeURIComponent(id)}/touch`, {})
      .catch(() => undefined);
  }, []);

  const disconnect = useCallback(async () => {
    if (closingRef.current) {
      return;
    }
    closingRef.current = true;
    const id = sessionIdRef.current;
    const ws = socketRef.current;
    rfbRef.current?.disconnect();
    rfbRef.current = null;
    socketRef.current = null;
    sessionIdRef.current = null;
    setSessionId(null);
    setConnected(false);
    setConnecting(false);
    ws?.close();
    if (id) {
      try {
        await teamApi.delete(`browser/sessions/${encodeURIComponent(id)}`);
      } catch {
        // 切断済みなら消えている。
      }
    }
    closingRef.current = false;
  }, []);

  const openBrowser = useCallback(async () => {
    const run = ++runRef.current;
    const stale = () => run !== runRef.current;
    setSessionError(null);
    await disconnect();
    if (stale()) {
      return;
    }
    setConnecting(true);
    const token = await getIdToken();
    if (stale()) {
      return;
    }
    if (!token) {
      setSessionError('認証が必要です。再ログインしてください。');
      setConnecting(false);
      return;
    }
    let created: BrowserSessionInfo;
    try {
      const res = await teamApi.post<{ session: BrowserSessionInfo }>('browser/sessions', {});
      created = res.data.session;
    } catch (e) {
      if (stale()) {
        return;
      }
      const data = e instanceof ApiError ? (e.data as { error?: string } | undefined) : undefined;
      setSessionError(data?.error || 'ブラウザを起動できませんでした。');
      setConnecting(false);
      return;
    }
    if (stale()) {
      try {
        await teamApi.delete(`browser/sessions/${encodeURIComponent(created.id)}`);
      } catch {
        // 破棄済みなら消えている。
      }
      return;
    }
    sessionIdRef.current = created.id;
    setSessionId(created.id);
    lastTouchRef.current = 0;
    const api = import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT as string;
    const hello = JSON.stringify({ token, sessionId: created.id });
    let openTimer = 0;

    const attach = (socket: ScreenSocket, terminal: boolean) => {
      let ready = false;
      let rejected = false;
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        window.clearTimeout(openTimer);
        socket.send(hello);
      };
      socket.onmessage = (ev) => {
        if (typeof ev.data !== 'string') {
          return;
        }
        let msg: { type?: string; message?: string };
        try {
          msg = JSON.parse(ev.data) as { type?: string; message?: string };
        } catch {
          return;
        }
        if (msg.type === 'ready') {
          ready = true;
          const target = screenRef.current;
          if (stale()) {
            void disconnect();
            return;
          }
          if (!target) {
            setSessionError('画面の初期化に失敗しました。');
            void disconnect();
            return;
          }
          socket.onmessage = null;
          const screen = splitControlSocket(socket as WebSocket, (text) => {
            try {
              const control = JSON.parse(text) as { type?: string; message?: string };
              if (control.type === 'error') {
                setSessionError(control.message || 'ブラウザの画面転送が切れました。');
              }
            } catch {
              // 画面データのテキストフレームは無視する。
            }
          });
          const rfb = new RFB(target, screen, { shared: true });
          rfb.scaleViewport = true;
          rfb.focusOnClick = false;
          rfb.showDotCursor = true;
          rfb.background = '#111827';
          rfbRef.current = rfb;
          setConnected(true);
          setConnecting(false);
          touch();
          return;
        }
        if (msg.type === 'error') {
          rejected = true;
          setSessionError(msg.message || 'ブラウザの画面転送が切れました。');
          setConnecting(false);
          setConnected(false);
        }
      };
      socket.onerror = () => {
        if (stale() || ready || !terminal) {
          return;
        }
        setSessionError((prev) => prev || '画面の転送に接続できませんでした。');
        setConnecting(false);
      };
      socket.onclose = () => {
        window.clearTimeout(openTimer);
        if (socketRef.current !== socket) {
          return;
        }
        if (!terminal && !ready && !rejected && !stale()) {
          openHttp();
          return;
        }
        setConnected(false);
        setConnecting(false);
        void disconnect();
      };
    };

    const openHttp = () => {
      const socket = createHttpBrowserSocket(
        `browser/sessions/${encodeURIComponent(created.id)}/stream`,
        `browser/sessions/${encodeURIComponent(created.id)}/input`,
      );
      socketRef.current = socket;
      attach(socket, true);
      socket.start();
    };

    const ws = new WebSocket(browserWsUrl(api));
    socketRef.current = ws;
    attach(ws, false);
    openTimer = window.setTimeout(() => {
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    }, SOCKET_OPEN_MS);
  }, [disconnect, touch]);

  useEffect(() => {
    if (!autoStart) {
      return;
    }
    void openBrowser();
    const onHide = () => {
      releaseBrowserMic();
      void disconnect();
    };
    window.addEventListener('pagehide', onHide);
    const viewWindow = screenRef.current?.ownerDocument.defaultView;
    if (viewWindow && viewWindow !== window) {
      viewWindow.addEventListener('pagehide', onHide);
    }
    return () => {
      runRef.current += 1;
      window.removeEventListener('pagehide', onHide);
      viewWindow?.removeEventListener('pagehide', onHide);
      void disconnect();
    };
  }, [autoStart, disconnect, openBrowser]);

  return {
    screenRef,
    rfbRef,
    sessionId,
    connected,
    connecting,
    sessionError,
    touch,
    openBrowser,
  };
};
