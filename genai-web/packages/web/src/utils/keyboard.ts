export const SUBMIT_KEY_STORAGE = 'submitKey';

export type SubmitKey = 'enter' | 'shiftEnter' | 'ctrlEnter';

export const DEFAULT_SUBMIT_KEY: SubmitKey = 'enter';

export const SUBMIT_KEY_OPTIONS: {
  value: SubmitKey;
  label: string;
  description: string;
}[] = [
  {
    value: 'enter',
    label: 'Enter で送信',
    description: 'Shift+Enter で改行',
  },
  {
    value: 'shiftEnter',
    label: 'Shift+Enter で送信',
    description: 'Enter で改行',
  },
  {
    value: 'ctrlEnter',
    label: 'Ctrl+Enter で送信（Mac は ⌘+Enter）',
    description: 'Enter で改行',
  },
];

type SubmitKeyEvent = Pick<KeyboardEvent, 'key' | 'shiftKey' | 'ctrlKey' | 'metaKey'> & {
  isComposing?: boolean;
  nativeEvent?: { isComposing?: boolean };
};

type SubmitKeyDownEvent = SubmitKeyEvent & {
  preventDefault: () => void;
  currentTarget: { form?: HTMLFormElement | null };
};

export const parseSubmitKey = (raw: string | null | undefined): SubmitKey => {
  if (raw === 'shiftEnter' || raw === 'ctrlEnter' || raw === 'enter') {
    return raw;
  }
  return DEFAULT_SUBMIT_KEY;
};

export const readSubmitKey = (): SubmitKey => {
  try {
    return parseSubmitKey(globalThis.localStorage?.getItem(SUBMIT_KEY_STORAGE));
  } catch {
    return DEFAULT_SUBMIT_KEY;
  }
};

/** 入力欄のショートカット案内文 */
export const submitKeyHint = (key: SubmitKey = readSubmitKey()): string => {
  switch (key) {
    case 'shiftEnter':
      return 'Shift+Enter で送信 / Enter で改行';
    case 'ctrlEnter':
      return 'Ctrl（⌘）+ Enter で送信 / Enter で改行';
    default:
      return 'Enter で送信 / Shift+Enter で改行';
  }
};

/** フォーム欄用。設定に依らず現行どおり */
export const ENTER_SUBMIT_HINT = submitKeyHint('enter');

const isComposingEvent = (e: SubmitKeyEvent): boolean =>
  e.isComposing ?? e.nativeEvent?.isComposing ?? false;

/** 指定した送信キーか（IME 変換確定中は常に false） */
export const isSubmitKey = (e: SubmitKeyEvent, key: SubmitKey = readSubmitKey()): boolean => {
  if (e.key !== 'Enter' || isComposingEvent(e)) {
    return false;
  }
  const shift = Boolean(e.shiftKey);
  const ctrl = Boolean(e.ctrlKey);
  const meta = Boolean(e.metaKey);
  switch (key) {
    case 'shiftEnter':
      return shift && !ctrl && !meta;
    case 'ctrlEnter':
      return (ctrl || meta) && !shift;
    default:
      return !shift && !ctrl && !meta;
  }
};

/** フォーム固定。Enter で送信（IME・Shift+Enter は除外） */
export const isEnterSubmitKey = (e: SubmitKeyEvent): boolean => isSubmitKey(e, 'enter');

const requestSubmitOn = (e: SubmitKeyDownEvent, key: SubmitKey): void => {
  if (!isSubmitKey(e, key)) {
    return;
  }
  e.preventDefault();
  e.currentTarget.form?.requestSubmit();
};

/** プロンプト入力。アカウント設定の送信キーに従う */
export const requestSubmitOnEnter = (e: SubmitKeyDownEvent): void => {
  requestSubmitOn(e, readSubmitKey());
};

/** フォーム欄。設定に依らず Enter で送信 */
export const requestEnterSubmit = (e: SubmitKeyDownEvent): void => {
  requestSubmitOn(e, 'enter');
};
