type SubmitKeyEvent = Pick<KeyboardEvent, 'key' | 'shiftKey'> & {
  isComposing?: boolean;
  nativeEvent?: { isComposing?: boolean };
};

type SubmitKeyDownEvent = SubmitKeyEvent & {
  preventDefault: () => void;
  currentTarget: { form?: HTMLFormElement | null };
};

/** 入力欄のショートカット案内文 */
export const submitKeyHint = 'Enter で送信 / Shift+Enter で改行';

/** Enter で送信（IME 変換確定中・Shift+Enter の改行は除外） */
export const isSubmitKey = (e: SubmitKeyEvent): boolean => {
  const isComposing = e.isComposing ?? e.nativeEvent?.isComposing ?? false;
  return e.key === 'Enter' && !e.shiftKey && !isComposing;
};

/** Enter で所属フォームを送信する（Shift+Enter・IME 変換中は何もしない） */
export const requestSubmitOnEnter = (e: SubmitKeyDownEvent): void => {
  if (!isSubmitKey(e)) {
    return;
  }
  e.preventDefault();
  e.currentTarget.form?.requestSubmit();
};
