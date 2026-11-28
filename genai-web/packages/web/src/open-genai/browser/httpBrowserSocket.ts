import { teamApi } from '@/lib/fetcher';
import { FRAME_BINARY, FRAME_TEXT, decodeFrames, encodeFrames, type BrowserFrame } from './browserFrames';

const FLUSH_MS = 40;
const FLUSH_BYTES = 32 * 1024;

export type BinaryTransport = {
  get: (path: string) => Promise<{ data: ArrayBuffer; status: number }>;
  post: (path: string, body: Uint8Array) => Promise<void>;
};

/**
 * noVNC に渡す WebSocket の代わり。
 * 最初のテキスト（接続パラメータ）はサーバがセッション ID で開くので送らない。
 */
export class HttpBrowserSocket {
  binaryType: BinaryType = 'arraybuffer';
  readyState: number = WebSocket.CONNECTING;
  protocol = '';
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: Event) => void) | null = null;

  private dropHandshake = true;
  private queued: BrowserFrame[] = [];
  private queuedBytes = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private flushing = false;
  private flushAgain = false;
  private stopped = false;

  constructor(
    private readonly streamPath: string,
    private readonly inputPath: string,
    private readonly transport: BinaryTransport,
  ) {}

  start(): void {
    if (this.readyState !== WebSocket.CONNECTING) {
      return;
    }
    this.readyState = WebSocket.OPEN;
    this.onopen?.(new Event('open'));
    void this.poll();
  }

  send(data: string | ArrayBuffer | Blob | ArrayBufferView): void {
    if (this.readyState !== WebSocket.OPEN) {
      return;
    }
    if (this.dropHandshake && typeof data === 'string') {
      this.dropHandshake = false;
      return;
    }
    if (typeof data === 'string') {
      this.enqueue(FRAME_TEXT, new TextEncoder().encode(data));
      return;
    }
    if (data instanceof Blob) {
      void data.arrayBuffer().then((buffer) => {
        if (!this.stopped) {
          this.enqueue(FRAME_BINARY, new Uint8Array(buffer));
        }
      });
      return;
    }
    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data as ArrayBuffer);
    this.enqueue(FRAME_BINARY, bytes.slice());
  }

  close(_code?: number, _reason?: string): void {
    this.finish();
  }

  private enqueue(kind: number, payload: Uint8Array): void {
    if (this.stopped) {
      return;
    }
    this.queued.push({ kind, payload });
    this.queuedBytes += payload.byteLength;
    if (this.queuedBytes >= FLUSH_BYTES) {
      void this.flush();
      return;
    }
    if (this.timer === null) {
      this.timer = setTimeout(() => {
        this.timer = null;
        void this.flush();
      }, FLUSH_MS);
    }
  }

  private async flush(): Promise<void> {
    if (this.flushing) {
      this.flushAgain = true;
      return;
    }
    this.flushing = true;
    try {
      do {
        this.flushAgain = false;
        const frames = this.queued.splice(0);
        this.queuedBytes = 0;
        if (frames.length === 0 || this.stopped) {
          break;
        }
        try {
          await this.transport.post(this.inputPath, encodeFrames(frames));
        } catch (error) {
          if (!this.stopped) {
            this.reportFailure(error);
          }
          return;
        }
      } while (this.flushAgain && !this.stopped);
    } finally {
      this.flushing = false;
    }
  }

  private async poll(): Promise<void> {
    while (!this.stopped) {
      const started = Date.now();
      let response: { data: ArrayBuffer; status: number };
      try {
        response = await this.transport.get(this.streamPath);
      } catch (error) {
        if (!this.stopped) {
          this.reportFailure(error);
        }
        return;
      }
      if (this.stopped) {
        return;
      }
      if (response.status === 204 || response.data.byteLength === 0) {
        if (Date.now() - started < 50) {
          await new Promise((resolve) => setTimeout(resolve, 200));
        }
        continue;
      }
      let frames: BrowserFrame[];
      try {
        frames = decodeFrames(new Uint8Array(response.data));
      } catch {
        this.onerror?.(new Event('error'));
        this.finish();
        return;
      }
      for (const frame of frames) {
        if (this.stopped) {
          return;
        }
        const data =
          frame.kind === FRAME_TEXT
            ? new TextDecoder().decode(frame.payload)
            : frame.payload.slice().buffer;
        this.onmessage?.(new MessageEvent('message', { data }));
      }
    }
  }

  private reportFailure(error: unknown): void {
    const data =
      error !== null && typeof error === 'object' && 'data' in error
        ? (error as { data?: { error?: unknown } }).data
        : undefined;
    const message = typeof data?.error === 'string' ? data.error : '';
    if (message) {
      this.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({ type: 'error', message }),
        }),
      );
    }
    this.onerror?.(new Event('error'));
    this.finish();
  }

  private finish(): void {
    if (this.stopped) {
      return;
    }
    this.stopped = true;
    this.readyState = WebSocket.CLOSED;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.onclose?.(new Event('close'));
  }
}

export const createHttpBrowserSocket = (streamPath: string, inputPath: string): HttpBrowserSocket =>
  new HttpBrowserSocket(streamPath, inputPath, {
    get: (path) => teamApi.getBinary(path),
    post: async (path, body) => {
      await teamApi.postBinary(path, body);
    },
  });
