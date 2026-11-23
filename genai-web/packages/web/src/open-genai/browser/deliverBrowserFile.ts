import { teamApi } from '@/lib/fetcher';

export type BrowserExportResult = {
  delivery?: string;
  object_key?: string;
  error?: string;
};

export const CARRIER_FALLBACK_NOTICE =
  '案内ファイルを作れなかったため、ファイル本体を保存しました。';

/** オフィスのダウンロードと同じく、見ている PC へファイルを渡す。 */
export const saveBrowserDownload = (name: string, bytes: ArrayBuffer) => {
  const safe = name.replace(/[/\\]/g, '_').trim() || 'download';
  const url = URL.createObjectURL(new Blob([bytes]));
  const link = document.createElement('a');
  link.href = url;
  link.download = safe;
  link.click();
  URL.revokeObjectURL(url);
};

export const deliverBrowserFile = async (
  name: string,
  bytes: ArrayBuffer,
  delivery: string | undefined,
  downloadCarrier: (objectKey: string) => Promise<void>,
): Promise<string | null> => {
  if (delivery !== 'carrier') {
    saveBrowserDownload(name, bytes);
    return null;
  }
  try {
    const safe = name.replace(/[/\\]/g, '_').trim() || 'download';
    const res = await teamApi.putBinary<BrowserExportResult>(
      `browser/export?name=${encodeURIComponent(safe)}`,
      new Blob([bytes]),
      { 'Content-Type': 'application/octet-stream' },
    );
    if (res.data.delivery === 'carrier' && res.data.object_key) {
      await downloadCarrier(res.data.object_key);
      return null;
    }
  } catch {
    // 案内ファイルを作れないときは本体を残す。
  }
  saveBrowserDownload(name, bytes);
  return CARRIER_FALLBACK_NOTICE;
};
