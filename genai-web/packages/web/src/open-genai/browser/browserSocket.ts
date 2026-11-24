/** noVNC に渡すソケット。テキストの制御メッセージは画面データから分ける。 */
export type ControlSocket = WebSocket;

export const splitControlSocket = (ws: WebSocket, onControl: (text: string) => void): WebSocket => {
  const proxy = {
    send: (data: Parameters<WebSocket['send']>[0]) => {
      ws.send(data);
    },
    close: (code?: number, reason?: string) => {
      ws.close(code, reason);
    },
    get binaryType() {
      return ws.binaryType;
    },
    set binaryType(value: BinaryType) {
      ws.binaryType = value;
    },
    onerror: null as ((ev: Event) => void) | null,
    onmessage: null as ((ev: MessageEvent) => void) | null,
    onopen: null as ((ev: Event) => void) | null,
    get protocol() {
      return ws.protocol;
    },
    get readyState() {
      return ws.readyState;
    },
  };
  const previousError = ws.onerror;
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') {
      onControl(ev.data);
      return;
    }
    proxy.onmessage?.(ev);
  };
  ws.onerror = (ev) => {
    proxy.onerror?.(ev);
    previousError?.call(ws, ev);
  };
  return proxy as unknown as WebSocket;
};
