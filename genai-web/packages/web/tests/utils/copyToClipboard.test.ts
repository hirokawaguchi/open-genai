import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyToClipboard } from '@/utils/copyToClipboard';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('copyToClipboard', () => {
  it('空文字は失敗する', async () => {
    await expect(copyToClipboard('')).resolves.toBe(false);
  });

  it('clipboard API が使えるときはそれを使う', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    await expect(copyToClipboard('http://example.test/public/x')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('http://example.test/public/x');
  });

  it('clipboard API が拒否されたら execCommand にフォールバックする', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('NotAllowedError')) },
    });
    // jsdom (vitest v4) は execCommand を実装しないため spyOn では失敗する。直接定義する。
    const exec = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      writable: true,
      value: exec,
    });
    await expect(copyToClipboard('abc')).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
  });
});
