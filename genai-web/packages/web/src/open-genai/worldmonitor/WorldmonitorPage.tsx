import { PageTitle } from '@/components/PageTitle';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { WORLDMONITOR_EXAPP_ID } from '@/layout/navItems';
import { useWorldmonitorConfig } from './useWorldmonitor';

/**
 * World Monitor 専用ページ。対局中の戦国国取りと同じく、ヘッダ直下の 1 画面に収める。
 * Compose profiles: ["worldmonitor"] 未起動時は有効化手順だけ出す。
 */
export const WorldmonitorPage = () => {
  const { documentTitle } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    WORLDMONITOR_EXAPP_ID,
    'ワールドモニター',
  );
  const { enabled, isLoading, error } = useWorldmonitorConfig();

  if (!isLoading && enabled) {
    return (
      <>
        <PageTitle title={documentTitle} />
        <iframe
          title={documentTitle}
          src='/worldmonitor-ui/'
          className='h-[calc(100dvh-var(--header-height))] w-full border-0 bg-black'
        />
      </>
    );
  }

  return (
    <>
      <PageTitle title={documentTitle} />
      <div className='flex h-[calc(100dvh-var(--header-height))] flex-col overflow-hidden p-3 lg:p-4'>
        {isLoading ? (
          <p className='text-std-14N-160 text-solid-gray-700'>読み込み中…</p>
        ) : (
          <div
            className='min-h-0 flex-1 overflow-auto rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3 text-std-14N-160 text-solid-gray-800'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              ワールドモニターは現在有効化されていません
            </p>
            <p className='mt-2'>{error || 'profile worldmonitor で起動してください。'}</p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130'>
              docker compose --profile worldmonitor up -d{'\n'}
              # または .env に COMPOSE_PROFILES=worldmonitor
            </pre>
          </div>
        )}
      </div>
    </>
  );
};
