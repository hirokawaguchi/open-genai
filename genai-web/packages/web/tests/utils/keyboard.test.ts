import { beforeEach, describe, expect, it, vi } from 'vitest';

const createKeyEvent = (
  overrides: Partial<{
    key: string;
    shiftKey: boolean;
    isComposing: boolean;
    nativeEvent: { isComposing?: boolean };
  }> = {},
) => ({
  key: 'Enter',
  shiftKey: false,
  ...overrides,
});

describe('keyboard utils', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('submitKeyHint はショートカット案内を返す', async () => {
    const { submitKeyHint } = await import('../../src/utils/keyboard');
    expect(submitKeyHint).toBe('Enter で送信 / Shift+Enter で改行');
  });

  it('Enter のみで isSubmitKey が true を返す', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent())).toBe(true);
  });

  it('Shift+Enter で isSubmitKey が false を返す', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent({ shiftKey: true }))).toBe(false);
  });

  it('IME 変換中（isComposing）は isSubmitKey が false を返す', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent({ isComposing: true }))).toBe(false);
    expect(isSubmitKey(createKeyEvent({ nativeEvent: { isComposing: true } }))).toBe(false);
  });

  it('Enter 以外のキーで isSubmitKey が false を返す', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent({ key: 'a' }))).toBe(false);
  });

  it('requestSubmitOnEnter は Enter で preventDefault と requestSubmit を呼ぶ', async () => {
    const { requestSubmitOnEnter } = await import('../../src/utils/keyboard');
    const preventDefault = vi.fn();
    const requestSubmit = vi.fn();
    requestSubmitOnEnter({
      ...createKeyEvent(),
      preventDefault,
      currentTarget: { form: { requestSubmit } as unknown as HTMLFormElement },
    });
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(requestSubmit).toHaveBeenCalledTimes(1);
  });

  it('requestSubmitOnEnter は Shift+Enter では何もしない', async () => {
    const { requestSubmitOnEnter } = await import('../../src/utils/keyboard');
    const preventDefault = vi.fn();
    const requestSubmit = vi.fn();
    requestSubmitOnEnter({
      ...createKeyEvent({ shiftKey: true }),
      preventDefault,
      currentTarget: { form: { requestSubmit } as unknown as HTMLFormElement },
    });
    expect(preventDefault).not.toHaveBeenCalled();
    expect(requestSubmit).not.toHaveBeenCalled();
  });
});
