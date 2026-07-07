import { teamApi } from '@/lib/fetcher';

const parseFilename = (disposition: string | null): string | null => {
  if (!disposition) {
    return null;
  }
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      return utf8[1];
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(disposition);
  return ascii?.[1] ?? null;
};

// 成果物のダウンロード URL を記載した「リンクファイル」を取得して端末に保存する。
// LGWAN 端末はこのファイルを持ち出し、インターネット接続端末で URL を開いて本体を取得する。
export const useDownloadArtifactCarrier = () => {
  const downloadCarrier = async (objectKey: string): Promise<void> => {
    const { blob, disposition } = await teamApi.getBlob('/exapps/artifact-carrier', {
      params: { objectKey },
    });

    const filename =
      parseFilename(disposition) ?? `${objectKey.split('/').pop() ?? 'download'}_link.txt`;
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  };

  return { downloadCarrier };
};
