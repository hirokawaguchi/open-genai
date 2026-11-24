import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { BrowserWindowPage } from './BrowserWindowPage';
import { getBrowserPipMount, subscribeBrowserPip } from './browserWindow';

/** アドレスバーのないウィンドウへ、起動ページが閉じても残る画面を出す。 */
export const BrowserPipHost = () => {
  const mount = useSyncExternalStore(subscribeBrowserPip, getBrowserPipMount, () => null);
  if (!mount) {
    return null;
  }
  return createPortal(<BrowserWindowPage />, mount);
};
