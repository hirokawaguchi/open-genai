import { Artifact, InvokeExAppRequest, InvokeExAppResponse } from 'genai-web';
import { ApiError, teamApi } from '@/lib/fetcher';
import { getIdToken } from '@/local/localAuth';

// dify-app -> backend が流す NDJSON の 1 行に対応するイベント。
export type ExAppStreamEvent =
  | { event: 'delta'; text: string }
  | { event: 'done'; outputs: string; artifacts?: Artifact[] }
  | { event: 'error'; error: string; error_code?: string };

export type ExAppStreamHandlers = {
  onDelta: (text: string) => void;
  onDone: (result: { outputs: string; artifacts?: Artifact[] }) => void;
  onError: (message: string, code?: string) => void;
};

export const useInvokeExApp = () => {
  const invokeExApp = async (request: InvokeExAppRequest) => {
    const response = await teamApi.post<InvokeExAppResponse>('exapps/invoke', request);
    return response.data;
  };

  /**
   * Dify チャット種別の AI アプリを NDJSON でストリーミング実行する。
   * バックエンドの /exapps/invoke/stream が改行区切り JSON を返すため、
   * 完全な 1 行ごとにパースしてハンドラへ渡す（predictStream と同型）。
   * ストリーム開始前の失敗（403/400/404 等）は ApiError を throw する。
   */
  const invokeExAppStream = async (
    request: InvokeExAppRequest,
    handlers: ExAppStreamHandlers,
  ): Promise<void> => {
    const token = await getIdToken();
    const res = await fetch(
      `${import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT}/exapps/invoke/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(request),
      },
    );

    if (!res.ok || !res.body) {
      const text = await res.text();
      let data: unknown = text;
      try {
        data = JSON.parse(text);
      } catch {
        // テキストのまま
      }
      throw new ApiError(res.status, data);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const handleLine = (line: string) => {
      if (line.trim().length === 0) {
        return;
      }
      let ev: ExAppStreamEvent;
      try {
        ev = JSON.parse(line) as ExAppStreamEvent;
      } catch {
        return;
      }
      if (ev.event === 'delta') {
        handlers.onDelta(ev.text ?? '');
      } else if (ev.event === 'done') {
        handlers.onDone({ outputs: ev.outputs ?? '', artifacts: ev.artifacts });
      } else if (ev.event === 'error') {
        handlers.onError(ev.error ?? '', ev.error_code);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let newlineIndex = buffer.indexOf('\n');
      while (newlineIndex !== -1) {
        handleLine(buffer.slice(0, newlineIndex));
        buffer = buffer.slice(newlineIndex + 1);
        newlineIndex = buffer.indexOf('\n');
      }
    }

    if (buffer.trim().length > 0) {
      handleLine(buffer);
    }
  };

  return {
    invokeExApp,
    invokeExAppStream,
  };
};
