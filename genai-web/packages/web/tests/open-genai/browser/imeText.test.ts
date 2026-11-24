import { describe, expect, it } from 'vitest';
import { isComposingKey, keysymsForText } from '@/open-genai/browser/imeText';

describe('keysymsForText', () => {
  it('半角文字は Latin-1 のキーシムにする', () => {
    expect(keysymsForText('A a')).toEqual([0x41, 0x20, 0x61]);
  });

  it('ひらがなと漢字は Unicode キーシムにする', () => {
    expect(keysymsForText('あ漢')).toEqual([0x01003042, 0x01006f22]);
  });

  it('カタカナをカナキーのキーシムにしない', () => {
    expect(keysymsForText('ア')).toEqual([0x010030a2]);
  });

  it('改行は送らない', () => {
    expect(keysymsForText('あ\nい')).toEqual([0x01003042, 0x01003044]);
  });
});

describe('isComposingKey', () => {
  it('変換中と Process キーを変換中とみなす', () => {
    expect(isComposingKey({ isComposing: true, keyCode: 65, key: 'a' })).toBe(true);
    expect(isComposingKey({ isComposing: false, keyCode: 229, key: 'Unidentified' })).toBe(true);
    expect(isComposingKey({ isComposing: false, keyCode: 0, key: 'Process' })).toBe(true);
    expect(isComposingKey({ isComposing: false, keyCode: 65, key: 'a' })).toBe(false);
  });
});
