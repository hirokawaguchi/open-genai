import { describe, expect, it } from 'vitest';
import { chaptersFromAnswer } from './chapters';

describe('chaptersFromAnswer', () => {
  it('見出しが無い回答は分けない', () => {
    expect(chaptersFromAnswer('対象は南九州市です。')).toEqual([]);
  });

  it('見出しごとに本文を分ける', () => {
    const text = ['# 背景', '現行は紙である[1]。', '', '## 目標', '電子化する。'].join('\n');
    expect(chaptersFromAnswer(text)).toEqual([
      { label: '背景', value: '現行は紙である。' },
      { label: '目標', value: '電子化する。' },
    ]);
  });

  it('最初の見出しより前の文は最初の章に残す', () => {
    const text = ['前置きです。', '', '# 背景', '本文。'].join('\n');
    expect(chaptersFromAnswer(text)).toEqual([{ label: '背景', value: '前置きです。\n\n本文。' }]);
  });

  it('章の本文では箇条書きの字下げを残し、出典行を捨てる', () => {
    const text = ['# 監査', '- **総合評価**', '  - 適合している[1]。', '  - 【出典】[1]'].join(
      '\n',
    );
    expect(chaptersFromAnswer(text)).toEqual([
      { label: '監査', value: '- **総合評価**\n  - 適合している。' },
    ]);
  });
});
