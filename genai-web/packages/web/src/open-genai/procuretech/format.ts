/** Content-Disposition ヘッダーからダウンロードファイル名を取り出す。 */
export const parseDownloadFilename = (
  disposition: string | null,
  fallback = 'systemplan.xlsx',
): string => {
  if (!disposition) return fallback;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      return utf8[1];
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(disposition);
  return ascii?.[1] ?? fallback;
};
