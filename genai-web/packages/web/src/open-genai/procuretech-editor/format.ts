// 情報化企画書エディタ用の小さな整形ユーティリティ（テスト対象）。

import type { EditorComposeFormat, EditorCompositionOutput } from './types';

export const EDITOR_COMPOSE_FORMATS: readonly EditorComposeFormat[] = [
  'docx',
  'html',
  'pptx',
  'txt',
  'md',
];

export const EDITOR_VISUAL_FORMATS: readonly EditorComposeFormat[] = ['docx', 'html', 'pptx'];

export const composeFormatOf = (
  out: Pick<EditorCompositionOutput, 'format'>,
): EditorComposeFormat =>
  out.format && (EDITOR_COMPOSE_FORMATS as readonly string[]).includes(out.format)
    ? out.format
    : 'docx';

export const isVisualComposeFormat = (fmt: EditorComposeFormat): boolean =>
  (EDITOR_VISUAL_FORMATS as readonly string[]).includes(fmt);

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

const imagePattern = (): RegExp => /!\[([^\]]*)\]\(([^)\n]*)\)/g;

/** src が外部 URL / data URI / 絶対パスかどうか（＝書き換え対象外）。 */
const isExternalSrc = (src: string): boolean =>
  /^(https?:)?\/\//.test(src) || src.startsWith('data:') || src.startsWith('/');

const safeDecode = (src: string): string => {
  try {
    return decodeURI(src);
  } catch {
    return src;
  }
};

/** `..` と `./` を畳んだ相対パス。先頭の `/` は付けない。 */
const normalizeRel = (path: string): string => {
  const parts: string[] = [];
  for (const seg of path.replace(/\\/g, '/').split('/')) {
    if (!seg || seg === '.') continue;
    if (seg === '..') {
      parts.pop();
      continue;
    }
    parts.push(seg);
  }
  return parts.join('/');
};

type ParsedImage = { src: string; title: string };

/**
 * 画像記法の `(...)` 内側からパスと title を取り出す。
 * `path`、`<path with spaces>`、`path%20name.png`、末尾の `"title"` に対応する。
 */
const parseImageInner = (inner: string): ParsedImage | null => {
  let body = inner.trim();
  if (!body) return null;
  let title = '';
  const titled = body.match(/^(.*)\s+"([^"]*)"\s*$/);
  if (titled) {
    body = titled[1].trim();
    title = titled[2];
  }
  if (body.startsWith('<') && body.endsWith('>') && body.length >= 2) {
    body = body.slice(1, -1).trim();
  }
  if (!body) return null;
  const decoded = safeDecode(body);
  // URL は `/` を畳む前に判定する（https:// が https:/ になると相対パス扱いになる）。
  if (isExternalSrc(decoded)) {
    return { src: decoded, title };
  }
  const src = normalizeRel(decoded);
  return src ? { src, title } : null;
};

/**
 * Markdown 本文から、案件フォルダ内の相対パス画像 src の一覧を重複なく取り出す。
 * 空白を含むファイル名、`<>` 囲み、%エンコードも対象。外部 URL・data URI・絶対パスは除外する。
 */
export const extractImageSources = (md: string): string[] => {
  const set = new Set<string>();
  for (const m of md.matchAll(imagePattern())) {
    const parsed = parseImageInner(m[2]);
    if (parsed && !isExternalSrc(parsed.src)) {
      set.add(parsed.src);
    }
  }
  return [...set];
};

/**
 * 本文中の画像 src を、開いている Markdown からの相対で案件内ファイルへ解決する。
 * 見つからなければ null。
 */
export const resolveProjectImagePath = (
  src: string,
  markdownRel: string,
  paths: readonly string[],
): string | null => {
  const set = new Set(paths);
  const normalized = normalizeRel(safeDecode(src));
  if (!normalized || isExternalSrc(normalized)) return null;
  if (set.has(normalized)) return normalized;
  const dir = dirOf(markdownRel);
  if (dir) {
    const joined = normalizeRel(`${dir}/${normalized}`);
    if (set.has(joined)) return joined;
  }
  return null;
};

/**
 * 本文へ挿入する画像記法。空白や括弧を含むパスは `<>` で囲み、
 * プレビューと書き出しがリンクではなく画像として扱うようにする。
 */
export const markdownImage = (alt: string, relPath: string): string => {
  const safeAlt = alt.replace(/[[\]]/g, '');
  const dest = /[\s()]/.test(relPath) ? `<${relPath}>` : relPath;
  return `![${safeAlt}](${dest})`;
};

/**
 * Markdown 本文中の相対パス画像 src を、与えられたマップ（相対パス→URL）で
 * 置き換えた文字列を返す（プレビュー表示専用。保存内容は書き換えない）。
 * マップに無い src はそのまま残す。
 */
export const rewriteImageSources = (md: string, map: Record<string, string>): string =>
  md.replace(imagePattern(), (whole, alt: string, inner: string) => {
    const parsed = parseImageInner(inner);
    if (!parsed || isExternalSrc(parsed.src)) {
      return whole;
    }
    const url = map[parsed.src];
    if (!url) return whole;
    const title = parsed.title ? ` "${parsed.title}"` : '';
    return `![${alt}](${url}${title})`;
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
