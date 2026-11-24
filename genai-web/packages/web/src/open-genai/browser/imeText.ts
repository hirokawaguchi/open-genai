/** Latin-1 はそのまま、それ以外は X11 の Unicode キーシムにする。 */
export const keysymForCodePoint = (codePoint: number): number => {
  if (codePoint <= 0xff) {
    return codePoint;
  }
  return 0x01000000 | codePoint;
};

/**
 * 変換を確定した文字列を、Chromium へ送るキーシム列にする。
 * 制御文字は含めない。カタカナを XK_kana_* にはしない。
 */
export const keysymsForText = (text: string): number[] => {
  const keysyms: number[] = [];
  for (const char of text) {
    const codePoint = char.codePointAt(0);
    if (codePoint === undefined || codePoint < 0x20 || codePoint === 0x7f) {
      continue;
    }
    keysyms.push(keysymForCodePoint(codePoint));
  }
  return keysyms;
};

/** 変換中のキーは遠隔へ送らず、ブラウザの入力方式に渡す。 */
export const isComposingKey = (event: {
  isComposing: boolean;
  keyCode: number;
  key: string;
}): boolean => event.isComposing || event.keyCode === 229 || event.key === 'Process';
