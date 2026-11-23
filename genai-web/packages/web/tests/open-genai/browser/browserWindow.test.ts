import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BROWSER_VIEW_ROOT_ID,
  BROWSER_WINDOW_PATH,
  getBrowserPipMount,
  openBrowserSurface,
  openBrowserWindow,
} from '@/open-genai/browser/browserWindow';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('openBrowserWindow', () => {
  it('新しいウィンドウは表示用のパスを開く', () => {
    const popup = { closed: false, focus: vi.fn() };
    const open = vi.fn(() => popup);
    vi.stubGlobal('open', open);
    expect(openBrowserWindow(null)).toBe(popup);
    expect(open).toHaveBeenCalledWith(
      BROWSER_WINDOW_PATH,
      'open-genai-browser',
      expect.stringContaining('popup=yes'),
    );
    expect(popup.focus).toHaveBeenCalled();
  });

  it('すでに表示中なら読み直さず前面へ出す', () => {
    const popup = { closed: false, focus: vi.fn() } as unknown as Window;
    const open = vi.fn();
    vi.stubGlobal('open', open);
    expect(openBrowserWindow(popup)).toBe(popup);
    expect(open).not.toHaveBeenCalled();
    expect(popup.focus).toHaveBeenCalled();
  });

  it('閉じたウィンドウは開き直す', () => {
    const closed = { closed: true, focus: vi.fn() } as unknown as Window;
    const popup = { closed: false, focus: vi.fn() };
    vi.stubGlobal(
      'open',
      vi.fn(() => popup),
    );
    expect(openBrowserWindow(closed)).toBe(popup);
  });

  it('ブロックされたときは null を返す', () => {
    vi.stubGlobal(
      'open',
      vi.fn(() => null),
    );
    expect(openBrowserWindow(null)).toBeNull();
  });
});

describe('openBrowserSurface', () => {
  it('アドレスバーのないウィンドウを開き、スタイルの基準を残す', async () => {
    const doc = document.implementation.createHTMLDocument('pip');
    const view = {
      document: doc,
      closed: false,
      focus: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as Window;
    const requestWindow = vi.fn(async () => view);
    vi.stubGlobal('documentPictureInPicture', { requestWindow, window: null });
    const opened = await openBrowserSurface(null);
    expect(opened).toBe(view);
    expect(requestWindow).toHaveBeenCalled();
    expect(doc.getElementById(BROWSER_VIEW_ROOT_ID)).not.toBeNull();
    expect(doc.querySelector('base')?.getAttribute('href')).toBe(document.baseURI);
    expect(getBrowserPipMount()?.id).toBe(BROWSER_VIEW_ROOT_ID);
  });

  it('すでに開いていれば読み直さない', async () => {
    const existing = { closed: false, focus: vi.fn() } as unknown as Window;
    const requestWindow = vi.fn();
    vi.stubGlobal('documentPictureInPicture', { requestWindow, window: existing });
    expect(await openBrowserSurface(null)).toBe(existing);
    expect(requestWindow).not.toHaveBeenCalled();
    expect(existing.focus).toHaveBeenCalled();
  });
});
