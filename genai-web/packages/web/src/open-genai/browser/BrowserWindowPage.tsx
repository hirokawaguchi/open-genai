import { useCallback, useState } from 'react';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { BROWSER_EXAPP_ID } from '@/layout/navItems';
import { armBrowserMic } from './browserMic';
import { useBrowserConfig } from './useBrowser';
import { useBrowserAudio } from './useBrowserAudio';
import { useBrowserDownloads } from './useBrowserDownloads';
import { useBrowserIme } from './useBrowserIme';
import { useBrowserSession } from './useBrowserSession';

/**
 * 別ウィンドウの中身。Open GENAI のヘッダは出さず、Chromium だけを表示する。
 */
export const BrowserWindowPage = () => {
  const { documentTitle } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    BROWSER_EXAPP_ID,
    'Web ブラウザ',
  );
  const { config, isLoading: configLoading, unavailable } = useBrowserConfig();
  const serviceUp = !unavailable && config?.enabled !== false;
  const ready = !configLoading && serviceUp;
  const { screenRef, rfbRef, sessionId, connected, connecting, sessionError, touch, openBrowser } =
    useBrowserSession(ready);
  const { imeRef, placeIme } = useBrowserIme(screenRef, rfbRef, connected, touch);
  const [notice, setNotice] = useState<string | null>(null);
  const showNotice = useCallback((text: string) => setNotice(text), []);
  useBrowserDownloads(sessionId, config?.delivery, showNotice);
  const { resume } = useBrowserAudio(sessionId, screenRef, showNotice);

  return (
    <>
      <PageTitle title={documentTitle} />
      <div
        className='relative h-dvh w-screen overflow-hidden bg-solid-gray-900'
        onPointerDown={(event) => {
          resume();
          placeIme(event);
        }}
      >
        <div ref={screenRef} className='absolute inset-0' onPointerMove={touch} onKeyDown={touch} />
        <textarea
          ref={imeRef}
          aria-label='文字入力'
          tabIndex={-1}
          autoCapitalize='none'
          autoCorrect='off'
          spellCheck={false}
          className='pointer-events-none absolute h-8 w-12 resize-none border-0 p-0 opacity-0 outline-none'
        />
        {!ready && !configLoading && (
          <div className='absolute inset-0 flex items-center justify-center bg-white p-6 text-std-16N-170 text-solid-gray-800'>
            <div>
              <p className='text-std-16B-150 text-solid-gray-900'>
                Web ブラウザは現在有効化されていません
              </p>
              <p className='mt-2'>
                {config?.error || 'コンテナを profiles: ["browser"] で起動してください。'}
              </p>
            </div>
          </div>
        )}
        {ready && !connected && (
          <p className='pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-dns-14N-130 text-solid-gray-300'>
            {sessionError ? '' : connecting ? '起動しています…' : '表示を準備しています…'}
          </p>
        )}
        {notice ? (
          <div className='pointer-events-none absolute inset-x-0 bottom-6 z-10 flex justify-center px-4'>
            <div
              className='pointer-events-auto flex max-w-xl flex-wrap items-center gap-x-3 gap-y-1 rounded-8 border border-solid-gray-420 bg-white px-4 py-2 text-std-14N-160 text-solid-gray-800 shadow-1'
              role='status'
            >
              <p>{notice}</p>
              <button
                type='button'
                className='text-solid-gray-700 underline'
                onClick={() => setNotice(null)}
              >
                閉じる
              </button>
            </div>
          </div>
        ) : null}
        {sessionError && (
          <div className='absolute inset-x-0 top-3 flex justify-center px-4'>
            <div className='flex items-center gap-3 rounded-8 bg-white px-4 py-2 text-dns-14N-130 text-error-1 shadow-1'>
              <p role='alert'>{sessionError}</p>
              <Button
                type='button'
                variant='outline'
                size='sm'
                onClick={() => {
                  armBrowserMic();
                  void openBrowser();
                }}
              >
                開き直す
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
};
