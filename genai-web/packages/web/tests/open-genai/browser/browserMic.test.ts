import { afterEach, describe, expect, it, vi } from 'vitest';
import { armBrowserMic, getBrowserMic, releaseBrowserMic } from '@/open-genai/browser/browserMic';

const liveStream = () =>
  ({
    getAudioTracks: () => [{ readyState: 'live' }],
    getTracks: () => [{ stop: vi.fn(), readyState: 'live' }],
  }) as unknown as MediaStream;

afterEach(() => {
  releaseBrowserMic();
  vi.unstubAllGlobals();
});

describe('armBrowserMic', () => {
  it('ブラウザを開く操作でマイクを取り、次の操作では取り直さない', async () => {
    const stream = liveStream();
    const getUserMedia = vi.fn(async () => stream);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    vi.stubGlobal(
      'AudioContext',
      class {
        state = 'running';
        resume() {
          return Promise.resolve();
        }
        close() {
          return Promise.resolve();
        }
      },
    );

    armBrowserMic();
    await Promise.resolve();
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(getBrowserMic().stream).toBe(stream);

    armBrowserMic();
    await Promise.resolve();
    expect(getUserMedia).toHaveBeenCalledOnce();
  });
});
