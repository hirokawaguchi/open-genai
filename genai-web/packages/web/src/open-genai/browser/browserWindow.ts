import { releaseBrowserMic } from './browserMic';

export const BROWSER_WINDOW_PATH = '/browser/window';
export const BROWSER_WINDOW_NAME = 'open-genai-browser';
export const BROWSER_VIEW_ROOT_ID = 'browser-view-root';

type PictureInPicture = {
  requestWindow: (options: { width: number; height: number }) => Promise<Window>;
  window: Window | null;
};

type ViewState = { mount: HTMLElement; win: Window } | null;

let viewState: ViewState = null;
const viewListeners = new Set<() => void>();

const viewSize = () => {
  const availW = window.screen.availWidth || 1280;
  const availH = window.screen.availHeight || 840;
  return {
    width: Math.round(Math.min(availW, Math.max(960, availW * 0.92))),
    height: Math.round(Math.min(availH, Math.max(640, availH * 0.92))),
  };
};

const pictureInPicture = (): PictureInPicture | null => {
  const api = (window as Window & { documentPictureInPicture?: PictureInPicture })
    .documentPictureInPicture;
  return api ?? null;
};

const publishView = (next: ViewState) => {
  viewState = next;
  for (const listener of viewListeners) {
    listener();
  }
};

export const getBrowserPipMount = (): HTMLElement | null => viewState?.mount ?? null;

export const subscribeBrowserPip = (listener: () => void) => {
  viewListeners.add(listener);
  return () => {
    viewListeners.delete(listener);
  };
};

/** 別ドキュメントでも、この画面の CSS が効くようにする。 */
export const prepareViewDocument = (doc: Document): HTMLElement => {
  doc.title = 'Web ブラウザ';
  const base = doc.createElement('base');
  base.href = document.baseURI;
  doc.head.replaceChildren(base);
  for (const node of document.querySelectorAll('link[rel="stylesheet"], style')) {
    if (node instanceof HTMLLinkElement) {
      const copy = node.cloneNode(true) as HTMLLinkElement;
      copy.href = node.href;
      doc.head.appendChild(copy);
      continue;
    }
    doc.head.appendChild(node.cloneNode(true));
  }
  try {
    doc.adoptedStyleSheets = [...document.adoptedStyleSheets];
  } catch {
    // 別ドキュメントへ移せないスタイルは、複製した style 要素に任せる。
  }
  doc.documentElement.style.height = '100%';
  doc.body.style.height = '100%';
  doc.body.style.margin = '0';
  doc.body.style.overflow = 'hidden';
  doc.body.style.background = '#111827';
  const mount = doc.createElement('div');
  mount.id = BROWSER_VIEW_ROOT_ID;
  mount.style.height = '100%';
  doc.body.replaceChildren(mount);
  return mount;
};

/**
 * 通常の新規ウィンドウ。ブラウザのアドレスバーが残るため、対応ブラウザでは使わない。
 * 渡されたウィンドウがまだ開いていれば、読み直さずに前面へ出す。
 */
export const openBrowserWindow = (existing: Window | null): Window | null => {
  if (existing && !existing.closed) {
    existing.focus();
    return existing;
  }
  const { width, height } = viewSize();
  const left = Math.max(0, window.screenX + Math.round((window.outerWidth - width) / 2));
  const top = Math.max(0, window.screenY + Math.round((window.outerHeight - height) / 2));
  const features = [
    'popup=yes',
    `width=${width}`,
    `height=${height}`,
    `left=${left}`,
    `top=${top}`,
  ].join(',');
  const opened = window.open(BROWSER_WINDOW_PATH, BROWSER_WINDOW_NAME, features);
  opened?.focus();
  return opened;
};

/**
 * アドレスバーのないウィンドウで Chromium を開く。
 * 未対応のブラウザだけ、アドレスバー付きの新規ウィンドウに戻す。
 */
export const openBrowserSurface = async (existing: Window | null): Promise<Window | null> => {
  const pip = pictureInPicture();
  if (!pip) {
    return openBrowserWindow(existing);
  }
  if (pip.window && !pip.window.closed) {
    pip.window.focus();
    return pip.window;
  }
  const { width, height } = viewSize();
  const view = await pip.requestWindow({ width, height });
  const mount = prepareViewDocument(view.document);
  publishView({ mount, win: view });
  view.addEventListener('pagehide', () => {
    if (viewState?.win === view) {
      publishView(null);
    }
    releaseBrowserMic();
  });
  return view;
};
