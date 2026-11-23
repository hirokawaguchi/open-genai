import { type PointerEvent as ReactPointerEvent, type RefObject, useEffect, useRef } from 'react';
import { isComposingKey, keysymsForText } from './imeText';

type KeySender = {
  sendKey: (keysym: number, code?: string, down?: boolean) => void;
};

const isPlainTextKey = (event: KeyboardEvent) =>
  event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;

/**
 * キャンバスは日本語入力の変換先にならない。
 * 見えない入力欄で PC 側の入力方式に変換させ、確定した文字だけを送る。
 */
export const useBrowserIme = (
  screenRef: RefObject<HTMLElement | null>,
  rfbRef: RefObject<KeySender | null>,
  active: boolean,
  onActivity: () => void,
) => {
  const imeRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const ime = imeRef.current;
    if (!active || !ime) {
      return;
    }
    let skipPlainInsertUntil = 0;
    const sendText = (text: string) => {
      const rfb = rfbRef.current;
      if (!rfb || !text) {
        return;
      }
      for (const keysym of keysymsForText(text)) {
        rfb.sendKey(keysym);
      }
      onActivity();
    };
    const forwardKey = (event: KeyboardEvent) => {
      const canvas = screenRef.current?.querySelector('canvas');
      if (!canvas) {
        return;
      }
      canvas.dispatchEvent(
        new KeyboardEvent(event.type, {
          key: event.key,
          code: event.code,
          location: event.location,
          repeat: event.repeat,
          ctrlKey: event.ctrlKey,
          shiftKey: event.shiftKey,
          altKey: event.altKey,
          metaKey: event.metaKey,
          bubbles: true,
          cancelable: true,
        }),
      );
    };
    const onKey = (event: KeyboardEvent) => {
      if (isComposingKey(event)) {
        return;
      }
      if (event.type === 'keydown' && isPlainTextKey(event)) {
        return;
      }
      if (
        event.type === 'keydown' &&
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === 'v'
      ) {
        return;
      }
      forwardKey(event);
      if (event.type === 'keydown') {
        event.preventDefault();
      }
    };
    const onBeforeInput = (event: InputEvent) => {
      if (
        event.inputType === 'insertCompositionText' ||
        event.inputType === 'deleteCompositionText'
      ) {
        return;
      }
      if (
        (event.inputType === 'insertText' || event.inputType === 'insertFromPaste') &&
        event.data
      ) {
        event.preventDefault();
        if (event.inputType === 'insertText' && performance.now() < skipPlainInsertUntil) {
          return;
        }
        sendText(event.data);
      }
    };
    const onCompositionEnd = (event: CompositionEvent) => {
      if (event.data) {
        skipPlainInsertUntil = performance.now() + 50;
        sendText(event.data);
      }
      ime.value = '';
    };
    ime.addEventListener('keydown', onKey);
    ime.addEventListener('keyup', onKey);
    ime.addEventListener('beforeinput', onBeforeInput);
    ime.addEventListener('compositionend', onCompositionEnd);
    ime.focus({ preventScroll: true });
    return () => {
      ime.removeEventListener('keydown', onKey);
      ime.removeEventListener('keyup', onKey);
      ime.removeEventListener('beforeinput', onBeforeInput);
      ime.removeEventListener('compositionend', onCompositionEnd);
    };
  }, [active, onActivity, rfbRef, screenRef]);

  const placeIme = (event: ReactPointerEvent<HTMLDivElement>) => {
    onActivity();
    const ime = imeRef.current;
    if (!ime) {
      return;
    }
    const box = event.currentTarget.getBoundingClientRect();
    ime.style.left = `${Math.max(0, event.clientX - box.left)}px`;
    ime.style.top = `${Math.max(0, event.clientY - box.top)}px`;
    ime.focus({ preventScroll: true });
  };

  return { imeRef, placeIme };
};
