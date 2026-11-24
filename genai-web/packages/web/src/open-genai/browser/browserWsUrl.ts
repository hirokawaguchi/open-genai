/** team API と同じオリジンのブラウザ WebSocket URL を組み立てる。 */
export const browserWsUrl = (
  apiEndpoint: string,
  location: Pick<Location, 'protocol' | 'host'> = window.location,
  path = '/browser/ws',
): string => {
  if (/^https?:\/\//i.test(apiEndpoint)) {
    const url = new URL(apiEndpoint);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const basePath = url.pathname.replace(/\/$/, '');
    url.pathname = `${basePath}${path}`;
    url.search = '';
    url.hash = '';
    return url.toString();
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const prefix = apiEndpoint.endsWith('/') ? apiEndpoint.slice(0, -1) : apiEndpoint;
  return `${proto}//${location.host}${prefix}${path}`;
};
