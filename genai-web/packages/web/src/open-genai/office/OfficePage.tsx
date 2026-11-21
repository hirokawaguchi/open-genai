import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { useDownloadArtifactCarrier } from '@/features/exapp/hooks/useDownloadArtifactCarrier';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { teamApi } from '@/lib/fetcher';
import { OFFICE_APPS, type OfficeAppId } from './kinds';
import { useOfficeConfig } from './useOffice';

type ExportResult = {
  delivery?: string;
  object_key?: string;
  error?: string;
};

const saveDownload = (name: string, bytes: ArrayBuffer) => {
  const safe = name.replace(/[/\\]/g, '_').trim() || 'document';
  const url = URL.createObjectURL(new Blob([bytes]));
  const link = document.createElement('a');
  link.href = url;
  link.download = safe;
  link.click();
  URL.revokeObjectURL(url);
};

const appOf = (id: OfficeAppId) => OFFICE_APPS.find((app) => app.id === id) ?? OFFICE_APPS[0];

/**
 * ibisOffice の専用ページ。文書・表計算・スライドで起動するファイルを分ける。
 * ダウンロードは成果物の配信設定に従う。open は端末へ本体を保存し、
 * carrier は SeaweedFS へ書いて案内ファイルを渡す。
 */
export const OfficePage = ({ appId }: { appId: OfficeAppId }) => {
  const app = appOf(appId);
  const [params] = useSearchParams();
  const localFile = params.get('local') === '1';
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { documentTitle } = useRegisteredAppMeta(COMMON_EXAPPS_TEAM_ID, app.id, app.label);
  const { enabled, isLoading, error, delivery } = useOfficeConfig();
  const { downloadCarrier } = useDownloadArtifactCarrier();
  const deliveryRef = useRef(delivery);
  deliveryRef.current = delivery;
  const [notice, setNotice] = useState<string | null>(null);
  const src = useMemo(() => {
    const query = new URLSearchParams({
      download: '1',
      origin: window.location.origin,
    });
    if (localFile) {
      query.set('local', '1');
    } else {
      query.set('open', `/office-ui/templates/${app.template}`);
    }
    return `/office-ui/?${query.toString()}`;
  }, [app.template, localFile]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { source?: string; type?: string; name?: string; bytes?: unknown };
      if (data?.source !== 'ibisoffice' || data.type !== 'download') return;
      if (!(data.bytes instanceof ArrayBuffer)) return;
      const name = typeof data.name === 'string' ? data.name : app.template;
      const bytes = data.bytes;
      void (async () => {
        if (deliveryRef.current !== 'carrier') {
          saveDownload(name, bytes);
          return;
        }
        try {
          const safe = name.replace(/[/\\]/g, '_').trim() || app.template;
          const res = await teamApi.putBinary<ExportResult>(
            `office/export?name=${encodeURIComponent(safe)}`,
            new Blob([bytes]),
            { 'Content-Type': 'application/octet-stream' },
          );
          if (res.data.delivery === 'carrier' && res.data.object_key) {
            await downloadCarrier(res.data.object_key);
            setNotice(null);
            return;
          }
        } catch {
          // 案内ファイルを作れないときは本体を残す。
        }
        saveDownload(name, bytes);
        setNotice('案内ファイルを作れなかったため、ファイル本体を保存しました。');
      })();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [app.template, downloadCarrier]);

  if (!isLoading && enabled) {
    return (
      <>
        <PageTitle title={documentTitle} />
        <div className='flex h-[calc(100dvh-var(--header-height))] flex-col'>
          {notice ? (
            <p
              className='border-b border-solid-gray-420 bg-solid-gray-50 px-4 py-2 text-std-14N-160 text-solid-gray-800'
              role='status'
            >
              {notice}
            </p>
          ) : null}
          <iframe
            ref={iframeRef}
            title={documentTitle}
            src={src}
            className='min-h-0 w-full flex-1 border-0 bg-white'
          />
        </div>
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
              {app.label}は現在有効化されていません
            </p>
            <p className='mt-2'>{error || 'profile office で起動してください。'}</p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130'>
              docker compose --profile office up -d --build{'\n'}# または .env に
              COMPOSE_PROFILES=office
            </pre>
            <p className='mt-3'>
              編集には WebGPU に対応したブラウザ（新しい Chrome、Edge、Safari）が必要です。
            </p>
          </div>
        )}
      </div>
    </>
  );
};
