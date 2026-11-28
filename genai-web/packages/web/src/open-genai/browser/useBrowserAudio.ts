import { type RefObject, useCallback, useEffect, useRef } from 'react';
import { getIdToken } from '@/local/localAuth';
import { getBrowserMic, subscribeBrowserMic } from './browserMic';
import { browserWsUrl } from './browserWsUrl';
import { createHttpBrowserSocket, type HttpBrowserSocket } from './httpBrowserSocket';
import { MicFramer, PLAYBACK_RATE, stereoS16ToFloat } from './pcm';

type AudioSocket = WebSocket | HttpBrowserSocket;

const SOCKET_OPEN_MS = 4000;

const viewOf = (screen: HTMLDivElement | null): Window =>
  screen?.ownerDocument.defaultView ?? window;

/**
 * Chromium の再生をスピーカーへ出し、マイクを Chromium の入力へ渡す。
 */
export const useBrowserAudio = (
  sessionId: string | null,
  screenRef: RefObject<HTMLDivElement | null>,
  onNotice: (text: string) => void,
) => {
  const ctxRef = useRef<AudioContext | null>(null);
  const wsRef = useRef<AudioSocket | null>(null);
  const nextTimeRef = useRef(0);
  const micRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const onNoticeRef = useRef(onNotice);
  onNoticeRef.current = onNotice;

  const detachMic = useCallback(() => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    micRef.current = null;
  }, []);

  const attachMic = useCallback(() => {
    const { stream, context } = getBrowserMic();
    const ws = wsRef.current;
    if (!stream || !context || context.state === 'closed') {
      return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    if (micRef.current === stream && processorRef.current) {
      return;
    }
    detachMic();
    void context.resume();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(2048, 1, 1);
    const framer = new MicFramer();
    const mute = context.createGain();
    mute.gain.value = 0;
    processor.onaudioprocess = (event) => {
      const socket = wsRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
      }
      const samples = event.inputBuffer.getChannelData(0);
      for (const frame of framer.push(samples, context.sampleRate)) {
        socket.send(frame);
      }
    };
    source.connect(processor);
    processor.connect(mute);
    mute.connect(context.destination);
    micRef.current = stream;
    processorRef.current = processor;
  }, [detachMic]);

  const context = useCallback(() => {
    const existing = ctxRef.current;
    if (existing && existing.state !== 'closed') {
      return existing;
    }
    const owner = viewOf(screenRef.current);
    const Ctx = (owner as unknown as { AudioContext: typeof AudioContext }).AudioContext;
    let created: AudioContext;
    try {
      created = new Ctx({ sampleRate: PLAYBACK_RATE });
    } catch {
      created = new Ctx();
    }
    ctxRef.current = created;
    nextTimeRef.current = 0;
    return created;
  }, [screenRef]);

  const resume = useCallback(() => {
    const ctx = ctxRef.current;
    if (ctx && ctx.state === 'suspended') {
      void ctx.resume();
    }
  }, []);

  const play = useCallback(
    (data: ArrayBuffer) => {
      const ctx = context();
      if (ctx.state !== 'running') {
        return;
      }
      const decoded = stereoS16ToFloat(data);
      if (!decoded) {
        return;
      }
      const buffer = ctx.createBuffer(2, decoded.left.length, PLAYBACK_RATE);
      const left = buffer.getChannelData(0);
      const right = buffer.getChannelData(1);
      for (let i = 0; i < decoded.left.length; i++) {
        left[i] = decoded.left[i] ?? 0;
        right[i] = decoded.right[i] ?? 0;
      }
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      const start = Math.max(ctx.currentTime, nextTimeRef.current);
      if (start - ctx.currentTime > 0.4) {
        nextTimeRef.current = ctx.currentTime;
      }
      const when = Math.max(ctx.currentTime, nextTimeRef.current);
      source.start(when);
      nextTimeRef.current = when + buffer.duration;
    },
    [context],
  );

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    let giveUp = false;
    let preferHttp = false;
    const bindAudio = (ws: AudioSocket) => {
      let sawReady = false;
      ws.binaryType = 'arraybuffer';
      ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const message = JSON.parse(event.data) as { type?: string; message?: string };
            if (message.type === 'ready') {
              sawReady = true;
              context();
              attachMic();
            }
            if (message.type === 'error' && message.message) {
              onNoticeRef.current(message.message);
              if (message.message === '音声を起動できませんでした') {
                giveUp = true;
              }
            }
          } catch {
            // 音声以外のテキストは無視する。
          }
          return;
        }
        if (event.data instanceof ArrayBuffer) {
          play(event.data);
        }
      };
      return {
        get sawReady() {
          return sawReady;
        },
        done: new Promise<void>((resolve) => {
          ws.onclose = () => resolve();
        }),
      };
    };
    const connect = async () => {
      const token = await getIdToken();
      if (cancelled || !token) {
        return;
      }
      const hello = JSON.stringify({ token, sessionId });
      const finish = async (socket: AudioSocket, opened: { sawReady: boolean; done: Promise<void> }) => {
        await opened.done;
        if (wsRef.current === socket) {
          wsRef.current = null;
        }
        return opened.sawReady;
      };
      if (!preferHttp) {
        const api = import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT as string;
        const ws = new WebSocket(browserWsUrl(api, window.location, '/browser/audio'));
        wsRef.current = ws;
        const opened = bindAudio(ws);
        const timer = window.setTimeout(() => {
          if (ws.readyState === WebSocket.CONNECTING) {
            ws.close();
          }
        }, SOCKET_OPEN_MS);
        ws.onopen = () => {
          window.clearTimeout(timer);
          ws.send(hello);
        };
        const sawReady = await finish(ws, opened);
        window.clearTimeout(timer);
        if (cancelled || giveUp || sawReady) {
          return;
        }
        preferHttp = true;
      }
      const http = createHttpBrowserSocket(
        `browser/sessions/${encodeURIComponent(sessionId)}/audio/stream`,
        `browser/sessions/${encodeURIComponent(sessionId)}/audio/input`,
      );
      wsRef.current = http;
      const opened = bindAudio(http);
      http.onopen = () => {
        http.send(hello);
      };
      http.start();
      await finish(http, opened);
    };
    const run = async () => {
      let failures = 0;
      while (!cancelled && !giveUp) {
        const started = Date.now();
        await connect();
        if (cancelled || giveUp) {
          return;
        }
        failures = Date.now() - started > 10_000 ? 0 : failures + 1;
        if (failures >= 3) {
          onNoticeRef.current('音声の転送が切れました');
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
    };
    void run();
    return () => {
      cancelled = true;
      detachMic();
      wsRef.current?.close();
      wsRef.current = null;
      void ctxRef.current?.close();
      ctxRef.current = null;
    };
  }, [attachMic, context, detachMic, play, sessionId]);

  useEffect(() => {
    attachMic();
    const stop = subscribeBrowserMic(attachMic);
    return () => {
      stop();
      detachMic();
    };
  }, [attachMic, detachMic]);

  return { resume };
};
