import { afterEach, describe, expect, it, vi } from 'vitest';
import { FRAME_BINARY, FRAME_TEXT, decodeFrames, encodeFrames } from '@/open-genai/browser/browserFrames';
import { HttpBrowserSocket, type BinaryTransport } from '@/open-genai/browser/httpBrowserSocket';

const idleTransport = (): BinaryTransport & { posted: Uint8Array[] } => {
  const posted: Uint8Array[] = [];
  return {
    posted,
    get: () => new Promise(() => undefined),
    post: async (_path, body) => {
      posted.push(body);
    },
  };
};

describe('HttpBrowserSocket', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('drops the opening text and posts later bytes as a binary frame', async () => {
    vi.useFakeTimers();
    const transport = idleTransport();
    const socket = new HttpBrowserSocket('stream', 'input', transport);
    socket.start();
    socket.send(JSON.stringify({ token: 't', sessionId: 's' }));
    socket.send(new Uint8Array([1, 2, 3]).buffer);
    await vi.advanceTimersByTimeAsync(40);
    expect(transport.posted).toHaveLength(1);
    const frames = decodeFrames(transport.posted[0] ?? new Uint8Array());
    expect(frames).toHaveLength(1);
    expect(frames[0]?.kind).toBe(FRAME_BINARY);
    expect(Array.from(frames[0]?.payload ?? [])).toEqual([1, 2, 3]);
    socket.close();
  });

  it('dispatches text and binary messages from one response', async () => {
    const payload = encodeFrames([
      { kind: FRAME_TEXT, payload: new TextEncoder().encode('{"type":"ready"}') },
      { kind: FRAME_BINARY, payload: new Uint8Array([9]) },
    ]);
    let release: (value: { data: ArrayBuffer; status: number }) => void = () => undefined;
    const transport: BinaryTransport = {
      get: () =>
        new Promise((resolve) => {
          release = resolve;
        }),
      post: async () => undefined,
    };
    const socket = new HttpBrowserSocket('stream', 'input', transport);
    const messages: unknown[] = [];
    socket.onmessage = (event) => {
      messages.push(event.data);
    };
    socket.start();
    release({
      data: payload.buffer.slice(payload.byteOffset, payload.byteOffset + payload.byteLength),
      status: 200,
    });
    await vi.waitFor(() => expect(messages).toHaveLength(2));
    expect(messages[0]).toBe('{"type":"ready"}');
    expect(messages[1]).toBeInstanceOf(ArrayBuffer);
    expect(Array.from(new Uint8Array(messages[1] as ArrayBuffer))).toEqual([9]);
    socket.close();
  });
});
