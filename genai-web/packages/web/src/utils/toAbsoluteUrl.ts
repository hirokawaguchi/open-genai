/** 相対パスを今見ているオリジン付きの絶対 URL にする。 */
export function toAbsoluteUrl(url: string, origin?: string): string {
  const trimmed = (url || '').trim();
  if (!trimmed) {
    return '';
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) {
    return trimmed;
  }
  const base =
    origin ?? (typeof window !== 'undefined' ? window.location.origin : '');
  if (!base) {
    return trimmed;
  }
  return `${base.replace(/\/$/, '')}${trimmed.startsWith('/') ? '' : '/'}${trimmed}`;
}
