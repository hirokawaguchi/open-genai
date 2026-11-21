import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { useDownloadArtifactCarrier } from '@/features/exapp/hooks/useDownloadArtifactCarrier';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { ApiError, teamApi } from '@/lib/fetcher';
import { ledgerError } from '../ledger/useLedger';
import type { LedgerFile, LedgerRow } from '../ledger/types';
import { stageOfficeFile } from './handoff';
import { OFFICE_APPS, type OfficeAppId } from './kinds';
import { useOfficeConfig } from './useOffice';

type ExportResult = {
  delivery?: string;
  object_key?: string;
  error?: string;
};

type OfficeSaveRow = LedgerRow & { conflict?: boolean };

type Binding = { rowId: string; fileId: string };

type OfficeNotice = {
  text: string;
  ledgerId?: string;
  rowId?: string;
};

const ledgerHref = (notice: OfficeNotice) =>
  notice.ledgerId && notice.rowId ? `/ledger/${notice.ledgerId}/card/${notice.rowId}` : '';

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

const bodyFileId = (files: LedgerFile[] | undefined) =>
  (files || []).find((file) => file.role === 'body')?.file_id || '';

const putOfficeFile = (name: string, bytes: ArrayBuffer, query: Record<string, string>) => {
  const params = new URLSearchParams({ name, ...query });
  return teamApi.putBinary<OfficeSaveRow>(
    `ledger/office/files?${params.toString()}`,
    new Blob([bytes]),
    { 'Content-Type': 'application/octet-stream' },
  );
};

/**
 * ibisOffice の専用ページ。文書・表計算・スライドで起動するファイルを分ける。
 * 保存と名前を付けて保存は文書台帳へ書き、ダウンロードは端末か案内ファイルのまま。
 */
export const OfficePage = ({ appId }: { appId: OfficeAppId }) => {
  const app = appOf(appId);
  const [params, setSearchParams] = useSearchParams();
  const boundRow = params.get('row') || '';
  const boundFile = params.get('file') || '';
  const keepBinding = params.get('bound') === '1';
  // 保存で URL に local を足しても、開いているエディタは読み直さない。
  const [openLocal] = useState(
    () => params.get('local') === '1' || Boolean(params.get('row') && params.get('file')),
  );
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const openedKey = useRef('');
  const bindingRef = useRef<Binding | null>(null);
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const { documentTitle } = useRegisteredAppMeta(COMMON_EXAPPS_TEAM_ID, app.id, app.label);
  const { enabled, isLoading, error, delivery } = useOfficeConfig();
  const { downloadCarrier } = useDownloadArtifactCarrier();
  const deliveryRef = useRef(delivery);
  deliveryRef.current = delivery;
  const [notice, setNotice] = useState<OfficeNotice | null>(null);
  const [staged, setStaged] = useState(false);
  const [stageError, setStageError] = useState<string | null>(null);
  const src = useMemo(() => {
    const query = new URLSearchParams({
      download: '1',
      origin: window.location.origin,
    });
    if (openLocal) {
      query.set('local', '1');
    } else {
      query.set('open', `/office-ui/templates/${app.template}`);
    }
    return `/office-ui/?${query.toString()}`;
  }, [app.template, openLocal]);

  useEffect(() => {
    if (isLoading || !enabled) return;
    const key = `${boundRow}:${boundFile}`;
    if (openedKey.current === key) return;
    let cancelled = false;
    setStaged(false);
    setStageError(null);
    void (async () => {
      try {
        if (boundRow && boundFile) {
          const row = await teamApi.get<LedgerRow>(`ledger/rows/${boundRow}`);
          const file = (row.data.files || []).find((item) => item.file_id === boundFile);
          if (!file) {
            throw new Error('missing');
          }
          const blob = await teamApi.getBlob(`ledger/rows/${boundRow}/files/${boundFile}`);
          await stageOfficeFile(file.name, new Uint8Array(await blob.blob.arrayBuffer()));
          if (cancelled) return;
          bindingRef.current = keepBinding ? { rowId: boundRow, fileId: boundFile } : null;
        } else if (!cancelled) {
          bindingRef.current = null;
        }
        if (!cancelled) {
          openedKey.current = key;
          setStaged(true);
        }
      } catch (e) {
        if (!cancelled) setStageError(ledgerError(e, 'ファイルを開けませんでした'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [boundFile, boundRow, enabled, isLoading, keepBinding]);

  useEffect(() => {
    const remember = (row: OfficeSaveRow) => {
      const fileId = bodyFileId(row.files);
      if (!row.id || !fileId) return;
      openedKey.current = `${row.id}:${fileId}`;
      bindingRef.current = { rowId: row.id, fileId };
      const next = new URLSearchParams(paramsRef.current);
      next.set('local', '1');
      next.set('row', row.id);
      next.set('file', fileId);
      next.set('bound', '1');
      setSearchParams(next, { replace: true });
    };
    const saveToLedger = async (name: string, bytes: ArrayBuffer, mode: 'save' | 'save-as') => {
      const binding = mode === 'save' ? bindingRef.current : null;
      const query: Record<string, string> = binding
        ? { row_id: binding.rowId, file_id: binding.fileId }
        : {};
      const created = async (row: OfficeSaveRow, text: string) => {
        remember(row);
        setNotice({ text, ledgerId: row.ledger_id, rowId: row.id });
      };
      try {
        const res = await putOfficeFile(name, bytes, query);
        await created(
          res.data,
          mode === 'save-as' ? '別名で文書台帳に残しました。' : '文書台帳に保存しました。',
        );
      } catch (e) {
        const data =
          e instanceof ApiError && e.data && typeof e.data === 'object'
            ? (e.data as { error?: string; conflict?: boolean })
            : undefined;
        try {
          if (e instanceof ApiError && e.status === 409 && data?.conflict && binding) {
            const overwrite = window.confirm(
              'このファイルは別の保存で更新されています。上書きしますか。取り消すと別名の行に残します。',
            );
            if (overwrite) {
              const res = await putOfficeFile(name, bytes, { ...query, force: '1' });
              await created(res.data, '文書台帳の本体を上書きしました。');
              return;
            }
            const res = await putOfficeFile(name, bytes, {});
            await created(res.data, '別名で文書台帳に残しました。');
            return;
          }
          if (e instanceof ApiError && e.status === 403 && (data?.error || '').includes('確定')) {
            const copy = window.confirm('確定の行は上書きできません。別名で下書きを残しますか。');
            if (!copy) {
              setNotice({ text: data?.error || '確定の行は上書きできません。' });
              return;
            }
            const res = await putOfficeFile(name, bytes, {});
            await created(res.data, '別名で文書台帳に残しました。');
            return;
          }
          if (e instanceof ApiError && (e.status === 502 || e.status === 503)) {
            saveDownload(name, bytes);
            setNotice({ text: '台帳に保存できなかったため、ファイル本体を端末へ保存しました。' });
            return;
          }
          setNotice({ text: ledgerError(e, '文書台帳に保存できませんでした') });
        } catch (retryError) {
          setNotice({ text: ledgerError(retryError, '文書台帳に保存できませんでした') });
        }
      }
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { source?: string; type?: string; name?: string; bytes?: unknown };
      if (data?.source !== 'ibisoffice') return;
      const name = typeof data.name === 'string' ? data.name : app.template;
      if (data.type === 'save' || data.type === 'save-as') {
        if (!(data.bytes instanceof ArrayBuffer)) {
          setNotice({ text: '保存の内容を受け取れませんでした。ページを読み込み直してください。' });
          return;
        }
        setNotice(null);
        void saveToLedger(name, data.bytes, data.type);
        return;
      }
      if (!(data.bytes instanceof ArrayBuffer)) return;
      const bytes = data.bytes;
      if (data.type !== 'download') return;
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
        setNotice({ text: '案内ファイルを作れなかったため、ファイル本体を保存しました。' });
      })();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [app.template, downloadCarrier, setSearchParams]);

  if (!isLoading && enabled && staged) {
    return (
      <>
        <PageTitle title={documentTitle} />
        <div className='relative flex h-[calc(100dvh-var(--header-height))] flex-col'>
          <iframe
            ref={iframeRef}
            title={documentTitle}
            src={src}
            className='min-h-0 w-full flex-1 border-0 bg-white'
          />
          {notice ? (
            <div className='pointer-events-none absolute inset-x-0 bottom-12 z-10 flex justify-center px-4'>
              <div
                className='pointer-events-auto flex max-w-xl flex-wrap items-center gap-x-3 gap-y-1 rounded-8 border border-solid-gray-420 bg-white px-4 py-2 text-std-14N-160 text-solid-gray-800 shadow-1'
                role='status'
              >
                <p>{notice.text}</p>
                {ledgerHref(notice) ? (
                  <Link to={ledgerHref(notice)} className='text-blue-900 underline'>
                    文書台帳で開く
                  </Link>
                ) : null}
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
        </div>
      </>
    );
  }

  return (
    <>
      <PageTitle title={documentTitle} />
      <div className='flex h-[calc(100dvh-var(--header-height))] flex-col overflow-hidden p-3 lg:p-4'>
        {isLoading || (enabled && !stageError) ? (
          <p className='text-std-14N-160 text-solid-gray-700'>
            {enabled ? 'ファイルを開いています。' : '読み込み中…'}
          </p>
        ) : (
          <div
            className='min-h-0 flex-1 overflow-auto rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3 text-std-14N-160 text-solid-gray-800'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              {stageError ? 'ファイルを開けませんでした' : `${app.label}は現在有効化されていません`}
            </p>
            <p className='mt-2'>
              {stageError || error || 'profile office で起動してください。'}
            </p>
            {stageError ? null : (
              <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130'>
                docker compose --profile office up -d --build{'\n'}# または .env に
                COMPOSE_PROFILES=office
              </pre>
            )}
            <p className='mt-3'>
              編集には WebGPU に対応したブラウザ（新しい Chrome、Edge、Safari）が必要です。
            </p>
          </div>
        )}
      </div>
    </>
  );
};
