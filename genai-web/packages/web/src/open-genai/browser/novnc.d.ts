declare module '@novnc/novnc' {
  export default class RFB extends EventTarget {
    constructor(
      target: HTMLElement,
      urlOrChannel: string | WebSocket,
      options?: { shared?: boolean },
    );
    scaleViewport: boolean;
    focusOnClick: boolean;
    showDotCursor: boolean;
    background: string;
    sendKey(keysym: number, code?: string, down?: boolean): void;
    disconnect(): void;
    focus(): void;
  }
}
