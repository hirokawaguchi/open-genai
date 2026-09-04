// 情報化企画書エディタ用の小さな整形ユーティリティ（テスト対象）。

/** バイト数を人間可読な文字列に整形する（例: 1536 → "1.5 KB"）。 */
export const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exp;
  const rounded = exp === 0 ? String(bytes) : value.toFixed(value >= 10 || value % 1 === 0 ? 0 : 1);
  return `${rounded} ${units[exp]}`;
};

/**
 * 相対パスからフォルダ部分（親ディレクトリ）を取り出す。ルート直下は空文字。
 * 例: "a/b/c.md" → "a/b" / "c.md" → ""
 */
export const dirOf = (relPath: string): string => {
  const idx = relPath.lastIndexOf('/');
  return idx === -1 ? '' : relPath.slice(0, idx);
};

/** 相対パスからファイル名部分を取り出す。 */
export const baseName = (relPath: string): string => {
  const idx = relPath.lastIndexOf('/');
  return idx === -1 ? relPath : relPath.slice(idx + 1);
};

/** File を data URL 付き base64 文字列へ変換する。 */
export const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('ファイルの読み込みに失敗しました'));
    reader.readAsDataURL(file);
  });

// Markdown 画像記法 `![alt](src "title")` を alt / src / title に分解する。
const MD_IMAGE_RE = /!\[([^\]]*)\]\(\s*([^)\s]+)((?:\s+"[^"]*")?)\s*\)/g;

/** src が外部 URL / data URI / 絶対パスかどうか（＝書き換え対象外）。 */
const isExternalSrc = (src: string): boolean =>
  /^(https?:)?\/\//.test(src) || src.startsWith('data:') || src.startsWith('/');

/**
 * Markdown 本文から、案件フォルダ内の相対パス画像 src の一覧を重複なく取り出す。
 * 外部 URL・data URI・絶対パスは除外する。
 */
export const extractImageSources = (md: string): string[] => {
  const set = new Set<string>();
  for (const m of md.matchAll(MD_IMAGE_RE)) {
    const src = decodeURI(m[2]);
    if (!isExternalSrc(src)) {
      set.add(src);
    }
  }
  return [...set];
};

/**
 * Markdown 本文中の相対パス画像 src を、与えられたマップ（相対パス→URL）で
 * 置き換えた文字列を返す（プレビュー表示専用。保存内容は書き換えない）。
 * マップに無い src はそのまま残す。
 */
export const rewriteImageSources = (md: string, map: Record<string, string>): string =>
  md.replace(MD_IMAGE_RE, (whole, alt: string, src: string, title: string) => {
    if (isExternalSrc(src)) {
      return whole;
    }
    const url = map[decodeURI(src)];
    return url ? `![${alt}](${url}${title})` : whole;
  });

/** URL からブラウザのダウンロードを起動する。 */
export const triggerDownload = (url: string, filename?: string): void => {
  const a = document.createElement('a');
  a.href = url;
  if (filename) {
    a.download = filename;
  }
  a.target = '_blank';
  a.rel = 'noopener';
  a.click();
};
