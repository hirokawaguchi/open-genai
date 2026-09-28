import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { DRAWIO_FRAME_SRC, downloadDataUri, safeFileName, xmlLooksConverted } from './drawio';

export type DrawioLoad =
  | { nonce: number; kind: 'xml'; xml: string }
  | { nonce: number; kind: 'mermaid'; mermaid: string }
  | { nonce: number; kind: 'blank' };

type DrawioEvent = {
  event?: string;
  xml?: string;
  data?: string;
  error?: string;
  spinKey?: string;
  message?: { spinKey?: string };
};

const spinKeyOf = (msg: DrawioEvent): string => msg.spinKey || msg.message?.spinKey || '';

export type DrawioFrameHandle = {
  exportImage: (format: 'png' | 'svg', title: string) => void;
};

type Props = {
  load: DrawioLoad;
  onConverted: (xml: string) => void;
  onConvertError: (message: string) => void;
  onAutosave: (xml: string) => void;
};

const CONVERT_ERROR = '図形に変換できませんでした。下書きは保存していません。';

export const DrawioFrame = forwardRef<DrawioFrameHandle, Props>((props, ref) => {
  const { load, onConverted, onConvertError, onAutosave } = props;
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const loadRef = useRef(load);
  const pendingExport = useRef<'png' | 'svg' | 'persist-draft' | null>(null);
  const settledNonce = useRef<number | null>(null);
  const downloadTitle = useRef('diagram');
  const callbacks = useRef({ onConverted, onConvertError, onAutosave });

  loadRef.current = load;
  callbacks.current = { onConverted, onConvertError, onAutosave };

  const post = (message: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(JSON.stringify(message), window.location.origin);
  };

  const sendLoad = () => {
    if (!readyRef.current) return;
    const current = loadRef.current;
    pendingExport.current = null;
    if (current.kind === 'mermaid') {
      post({
        action: 'load',
        descriptor: { format: 'mermaid', data: current.mermaid, wrap: true },
        autosave: 1,
        fit: 1,
      });
      return;
    }
    const xml = current.kind === 'xml' ? current.xml : '';
    post({
      action: 'load',
      xml,
      autosave: 1,
      fit: 1,
    });
  };

  useImperativeHandle(ref, () => ({
    exportImage: (format, title) => {
      downloadTitle.current = title;
      pendingExport.current = format;
      post({ action: 'export', format, spinKey: format });
    },
  }));

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (event.source !== iframeRef.current?.contentWindow) return;
      let msg: DrawioEvent;
      try {
        msg = typeof event.data === 'string' ? (JSON.parse(event.data) as DrawioEvent) : event.data;
      } catch {
        return;
      }
      if (!msg || typeof msg !== 'object') return;

      if (msg.event === 'init') {
        readyRef.current = true;
        sendLoad();
        return;
      }
      if (msg.event === 'load') {
        if (msg.error) {
          settledNonce.current = loadRef.current.nonce;
          callbacks.current.onConvertError(CONVERT_ERROR);
          return;
        }
        if (loadRef.current.kind === 'mermaid') {
          pendingExport.current = 'persist-draft';
          post({ action: 'export', format: 'xml', spinKey: 'persist-draft' });
        }
        return;
      }
      if (msg.event === 'export') {
        const key = spinKeyOf(msg) || pendingExport.current || '';
        if (key === 'persist-draft') {
          pendingExport.current = null;
          const xml = msg.xml || '';
          settledNonce.current = loadRef.current.nonce;
          if (!xml || !xmlLooksConverted(xml)) {
            callbacks.current.onConvertError(CONVERT_ERROR);
            return;
          }
          callbacks.current.onConverted(xml);
          return;
        }
        if ((key === 'png' || key === 'svg') && msg.data) {
          pendingExport.current = null;
          downloadDataUri(msg.data, safeFileName(downloadTitle.current, key));
        }
        return;
      }
      if ((msg.event === 'autosave' || msg.event === 'save') && msg.xml) {
        if (loadRef.current.kind === 'xml') {
          callbacks.current.onAutosave(msg.xml);
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  useEffect(() => {
    const nonce = load.nonce;
    const timer = window.setTimeout(() => {
      if (settledNonce.current === nonce) return;
      if (loadRef.current.kind === 'mermaid' && loadRef.current.nonce === nonce) {
        settledNonce.current = nonce;
        callbacks.current.onConvertError(CONVERT_ERROR);
      }
    }, 20000);
    if (readyRef.current) {
      sendLoad();
    }
    return () => window.clearTimeout(timer);
  }, [load.nonce]);

  return (
    <iframe
      ref={iframeRef}
      title='図の編集'
      src={DRAWIO_FRAME_SRC}
      className='h-full min-h-[28rem] w-full border-0'
    />
  );
});

DrawioFrame.displayName = 'DrawioFrame';
