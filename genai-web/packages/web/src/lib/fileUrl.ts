/**
 * `/files/` の URL を、今開いているページと同じホストのパスにする。
 * 保存値が絶対 URL でも、相対パスでも、img と fetch はページのホストへ向かう。
 */
export const pageFileUrl = (fileUrl: string): string => {
  if (
    !fileUrl ||
    fileUrl.startsWith('/') ||
    fileUrl.startsWith('data:') ||
    fileUrl.startsWith('blob:')
  ) {
    return fileUrl;
  }
  try {
    const url = new URL(fileUrl);
    if (url.pathname.includes('/files/')) {
      return `${url.pathname}${url.search}`;
    }
  } catch {
    return fileUrl;
  }
  return fileUrl;
};

/**
 * アップロード URL からストレージ上のオブジェクトキーを取り出す。
 *
 * PUBLIC_BASE_URL が `https://host/api` のとき pathname は `/api/files/<key>` になる。
 * 先頭の `/api` をキーに含めると削除・文字起こし開始などが誤動作する。
 *
 * @returns 例: `<uuid>/<filename>`（先頭の `files/` は含まない）
 */
export const fileObjectKeyFromUrl = (fileUrl: string): string | undefined => {
  try {
    const absolute = fileUrl.startsWith('/')
      ? new URL(fileUrl, 'http://localhost')
      : new URL(fileUrl);
    const pathname = decodeURIComponent(absolute.pathname);
    const marker = '/files/';
    const idx = pathname.indexOf(marker);
    if (idx >= 0) {
      const key = pathname.slice(idx + marker.length);
      return key || undefined;
    }

    let stripped = pathname.replace(/^\//, '');
    if (stripped.startsWith('api/')) {
      stripped = stripped.slice('api/'.length);
    }
    if (stripped.startsWith('files/')) {
      stripped = stripped.slice('files/'.length);
    }
    return stripped || undefined;
  } catch {
    return undefined;
  }
};
