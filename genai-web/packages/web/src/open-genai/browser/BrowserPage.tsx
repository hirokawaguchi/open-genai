import { useRef, useState, useSyncExternalStore } from 'react';
import { PiGlobeBold } from 'react-icons/pi';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { BROWSER_EXAPP_ID } from '@/layout/navItems';
import {
  armBrowserMic,
  clearBrowserMicNotice,
  getBrowserMic,
  getServerBrowserMic,
  releaseBrowserMic,
  subscribeBrowserMic,
} from './browserMic';
import { openBrowserSurface } from './browserWindow';
import { useBrowserConfig } from './useBrowser';

/**
 * Web ブラウザの起動ページ。
 * Chromium 本体は別ウィンドウに表示する。
 * Compose profiles: ["browser"] 未起動時は有効化手順を案内する。
 */
export const BrowserPage = () => {
  const { documentTitle } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    BROWSER_EXAPP_ID,
    'Web ブラウザ',
  );
  const { config, isLoading: configLoading, unavailable } = useBrowserConfig();
  const serviceUp = !unavailable && config?.enabled !== false;
  const [blocked, setBlocked] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const mic = useSyncExternalStore(subscribeBrowserMic, getBrowserMic, getServerBrowserMic);

  return (
    <>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-4 p-6 lg:p-8'>
        <h1 className='text-std-20B-150'>{documentTitle}</h1>
        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3 text-std-14N-160 text-solid-gray-800'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              Web ブラウザは現在有効化されていません
            </p>
            <p className='mt-2'>
              {config?.error || 'コンテナを profiles: ["browser"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130'>
              docker compose --profile browser up -d{'\n'}# または .env に COMPOSE_PROFILES=browser
            </pre>
          </div>
        )}
        {serviceUp && (
          <div className='flex flex-col items-start gap-3'>
            <p className='text-std-16N-170 text-solid-gray-700'>
              コンテナ型のセキュアブラウザです。ファイルの入出力は制御されています。スピーカーとマイクは使うことができます。
            </p>
            <Button
              type='button'
              variant='solid-fill'
              size='md'
              onClick={() => {
                armBrowserMic();
                void openBrowserSurface(popupRef.current)
                  .then((opened) => {
                    popupRef.current = opened;
                    setBlocked(!opened);
                    const pip = (
                      window as Window & { documentPictureInPicture?: { window: Window | null } }
                    ).documentPictureInPicture;
                    if (!opened || (opened !== window && opened !== pip?.window)) {
                      releaseBrowserMic();
                    }
                  })
                  .catch(() => {
                    setBlocked(true);
                    releaseBrowserMic();
                  });
              }}
            >
              <span className='inline-flex items-center gap-2'>
                <PiGlobeBold aria-hidden />
                ブラウザを開く
              </span>
            </Button>
            {mic.notice ? (
              <p className='text-dns-16N-130 text-error-1' role='alert'>
                {mic.notice}{' '}
                <button type='button' className='underline' onClick={clearBrowserMicNotice}>
                  閉じる
                </button>
              </p>
            ) : null}
            {blocked && (
              <p className='text-dns-16N-130 text-error-1' role='alert'>
                別ウィンドウを開けませんでした。ポップアップを許可してから、もう一度開いてください。
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
};
