import { beforeEach, describe, expect, it, vi } from 'vitest';

const createKeyEvent = (
  overrides: Partial<{
    key: string;
    shiftKey: boolean;
    ctrlKey: boolean;
    metaKey: boolean;
    isComposing: boolean;
    nativeEvent: { isComposing?: boolean };
  }> = {},
) => ({
  key: 'Enter',
  shiftKey: false,
  ctrlKey: false,
  metaKey: false,
  ...overrides,
});

describe('keyboard utils', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it('submitKeyHint の既定は現行の Enter 送信', async () => {
    const { submitKeyHint, ENTER_SUBMIT_HINT } = await import('../../src/utils/keyboard');
    expect(submitKeyHint()).toBe('Enter で送信 / Shift+Enter で改行');
    expect(ENTER_SUBMIT_HINT).toBe('Enter で送信 / Shift+Enter で改行');
    expect(submitKeyHint('shiftEnter')).toBe('Shift+Enter で送信 / Enter で改行');
    expect(submitKeyHint('ctrlEnter')).toBe('Ctrl（⌘）+ Enter で送信 / Enter で改行');
  });

  it('未設定では Enter のみで isSubmitKey が true', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent())).toBe(true);
  });

  it('未設定では Shift+Enter で isSubmitKey が false', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent({ shiftKey: true }))).toBe(false);
  });

  it('shiftEnter では Shift+Enter だけ送信', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent(), 'shiftEnter')).toBe(false);
    expect(isSubmitKey(createKeyEvent({ shiftKey: true }), 'shiftEnter')).toBe(true);
    expect(isSubmitKey(createKeyEvent({ ctrlKey: true }), 'shiftEnter')).toBe(false);
  });

  it('ctrlEnter では Ctrl または ⌘ + Enter だけ送信', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent(), 'ctrlEnter')).toBe(false);
    expect(isSubmitKey(createKeyEvent({ ctrlKey: true }), 'ctrlEnter')).toBe(true);
    expect(isSubmitKey(createKeyEvent({ metaKey: true }), 'ctrlEnter')).toBe(true);
    expect(isSubmitKey(createKeyEvent({ ctrlKey: true, shiftKey: true }), 'ctrlEnter')).toBe(false);
  });

  it('IME 変換中はどのモードでも isSubmitKey が false', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent({ isComposing: true }))).toBe(false);
    expect(isSubmitKey(createKeyEvent({ nativeEvent: { isComposing: true } }), 'shiftEnter')).toBe(
      false,
    );
    expect(isSubmitKey(createKeyEvent({ ctrlKey: true, isComposing: true }), 'ctrlEnter')).toBe(
      false,
    );
  });

  it('Enter 以外のキーで isSubmitKey が false を返す', async () => {
    const { isSubmitKey } = await import('../../src/utils/keyboard');
    expect(isSubmitKey(createKeyEvent({ key: 'a' }))).toBe(false);
  });

  it('isEnterSubmitKey は設定に依らず Enter 送信', async () => {
    const { isEnterSubmitKey, SUBMIT_KEY_STORAGE } = await import('../../src/utils/keyboard');
    localStorage.setItem(SUBMIT_KEY_STORAGE, 'ctrlEnter');
    expect(isEnterSubmitKey(createKeyEvent())).toBe(true);
    expect(isEnterSubmitKey(createKeyEvent({ ctrlKey: true }))).toBe(false);
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

  it('requestEnterSubmit は localStorage が ctrlEnter でも Enter で送信する', async () => {
    const { requestEnterSubmit, SUBMIT_KEY_STORAGE } = await import('../../src/utils/keyboard');
    localStorage.setItem(SUBMIT_KEY_STORAGE, 'ctrlEnter');
    const preventDefault = vi.fn();
    const requestSubmit = vi.fn();
    requestEnterSubmit({
      ...createKeyEvent(),
      preventDefault,
      currentTarget: { form: { requestSubmit } as unknown as HTMLFormElement },
    });
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(requestSubmit).toHaveBeenCalledTimes(1);
  });
});
