// @uiw/react-md-editor は Tab を横取りして空白を挿入する（tabSize 2 なら半角空白 4 つ）。
// 日本語変換の予測候補を Tab で選ぶと、その空白が本文に入って文章が崩れる。
export const editorTabSpaces = (tabSize = 2): string => '  '.repeat(Math.max(0, tabSize));

export type ImeTabGate = {
  composing: boolean;
  // compositionend の直後に届く Tab は、候補確定の余韻なのでインデントしない。
  swallowTab: boolean;
};

export const initialImeTabGate = (): ImeTabGate => ({ composing: false, swallowTab: false });

type TabKey = {
  key: string;
  code: string;
  keyCode: number;
  isComposing: boolean;
};

export const isTabKey = (event: { key: string; code: string }): boolean =>
  event.key === 'Tab' || event.code === 'Tab';

/** 変換中・変換確定直後の Tab は予測候補の選択なので、エディタのインデントにしない。 */
export const isImeTab = (event: TabKey, gate: ImeTabGate): boolean => {
  if (!isTabKey(event)) return false;
  return event.isComposing || event.keyCode === 229 || gate.composing || gate.swallowTab;
};

const SWALLOW_MS = 100;

/** macOS は Tab でインライン予測候補を確定する。ここで Tab を横取りすると本文が崩れる。 */
export const isMacLike = (): boolean =>
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '');

/**
 * エディタの textarea に Tab ガードを付ける。
 * 変換中の Tab は止める。macOS では、予測候補が入ったかを見てから
 * 入っていなければ従来どおり空白を挿入する。
 */
export const bindEditorImeTabGuard = (root: HTMLElement, systemTab = isMacLike()): (() => void) => {
  const textarea = root.querySelector('textarea');
  if (!textarea) return () => undefined;

  let composing = false;
  let swallowTab = false;
  let swallowTimer = 0;
  let pendingTimer = 0;
  let pendingInput: (() => void) | null = null;

  const onCompositionStart = () => {
    composing = true;
    swallowTab = false;
    window.clearTimeout(swallowTimer);
  };
  const onCompositionEnd = () => {
    composing = false;
    swallowTab = true;
    window.clearTimeout(swallowTimer);
    swallowTimer = window.setTimeout(() => {
      swallowTab = false;
    }, SWALLOW_MS);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.target !== textarea) return;
    if (!isTabKey(event)) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;

    if (isImeTab(event, { composing, swallowTab })) {
      event.stopPropagation();
      event.preventDefault();
      swallowTab = false;
      window.clearTimeout(swallowTimer);
      return;
    }
    // 範囲選択や Shift+Tab はエディタのインデント／アウトデントに任せる。
    if (!systemTab || event.shiftKey || textarea.selectionStart !== textarea.selectionEnd) return;

    // ここでエディタの keydown を止める。preventDefault しないので、
    // macOS の予測候補はシステム側が本文へ入れられる。
    event.stopPropagation();
    const before = textarea.value;
    let sawInput = false;
    if (pendingInput) textarea.removeEventListener('input', pendingInput);
    const onInput = () => {
      if (textarea.value !== before) sawInput = true;
    };
    pendingInput = onInput;
    textarea.addEventListener('input', onInput);
    window.clearTimeout(pendingTimer);
    pendingTimer = window.setTimeout(() => {
      textarea.removeEventListener('input', onInput);
      if (pendingInput === onInput) pendingInput = null;
      if (!textarea.isConnected) return;
      if (sawInput || textarea.value !== before) {
        if (document.activeElement !== textarea) textarea.focus({ preventScroll: true });
        return;
      }
      insertTabSpaces(textarea, editorTabSpaces());
    }, 0);
  };

  textarea.addEventListener('compositionstart', onCompositionStart);
  textarea.addEventListener('compositionend', onCompositionEnd);
  root.addEventListener('keydown', onKeyDown, true);
  return () => {
    window.clearTimeout(swallowTimer);
    window.clearTimeout(pendingTimer);
    if (pendingInput) textarea.removeEventListener('input', pendingInput);
    textarea.removeEventListener('compositionstart', onCompositionStart);
    textarea.removeEventListener('compositionend', onCompositionEnd);
    root.removeEventListener('keydown', onKeyDown, true);
  };
};

export const insertTabSpaces = (textarea: HTMLTextAreaElement, spaces: string) => {
  textarea.focus({ preventScroll: true });
  const start = textarea.selectionStart ?? 0;
  const end = textarea.selectionEnd ?? textarea.selectionStart ?? 0;
  let inserted = false;
  try {
    inserted =
      typeof document.execCommand === 'function' &&
      document.execCommand('insertText', false, spaces);
  } catch {
    inserted = false;
  }
  if (inserted) return;
  textarea.setRangeText(spaces, start, end, 'end');
  textarea.dispatchEvent(
    new InputEvent('input', { bubbles: true, data: spaces, inputType: 'insertText' }),
  );
};
