import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CARRIER_FALLBACK_NOTICE,
  deliverBrowserFile,
} from '@/open-genai/browser/deliverBrowserFile';

const putBinary = vi.fn();

vi.mock('@/lib/fetcher', () => ({
  teamApi: {
    putBinary: (...args: unknown[]) => putBinary(...args),
  },
}));

const bytes = () => new TextEncoder().encode('hello').buffer;

afterEach(() => {
  putBinary.mockReset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const stubSave = () => {
  const click = vi.fn();
  const real = document.createElement.bind(document);
  vi.stubGlobal('URL', {
    createObjectURL: () => 'blob:file',
    revokeObjectURL: () => undefined,
  });
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    const el = real(tag);
    if (tag === 'a') {
      el.click = click;
    }
    return el;
  });
  return click;
};

describe('deliverBrowserFile', () => {
  it('open では本体を保存し、案内ファイルは作らない', async () => {
    const click = stubSave();
    const carrier = vi.fn();
    await expect(deliverBrowserFile('memo.txt', bytes(), 'open', carrier)).resolves.toBeNull();
    expect(putBinary).not.toHaveBeenCalled();
    expect(carrier).not.toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
  });

  it('carrier では案内ファイルを保存する', async () => {
    putBinary.mockResolvedValue({ data: { delivery: 'carrier', object_key: 'obj/1' } });
    const click = stubSave();
    const carrier = vi.fn(async () => undefined);
    await expect(deliverBrowserFile('memo.txt', bytes(), 'carrier', carrier)).resolves.toBeNull();
    expect(putBinary).toHaveBeenCalledWith('browser/export?name=memo.txt', expect.any(Blob), {
      'Content-Type': 'application/octet-stream',
    });
    expect(carrier).toHaveBeenCalledWith('obj/1');
    expect(click).not.toHaveBeenCalled();
  });

  it('案内ファイルを作れないときは本体を保存して知らせる', async () => {
    putBinary.mockRejectedValue(new Error('down'));
    const click = stubSave();
    const carrier = vi.fn();
    await expect(deliverBrowserFile('memo.txt', bytes(), 'carrier', carrier)).resolves.toBe(
      CARRIER_FALLBACK_NOTICE,
    );
    expect(click).toHaveBeenCalled();
  });
});
