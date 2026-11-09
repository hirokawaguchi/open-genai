import { describe, expect, it } from 'vitest';
import { stripCitationMarks } from './formatMarkdown';

describe('stripCitationMarks', () => {
  it('文中の引用番号だけを消す', () => {
    expect(stripCitationMarks('現行は紙である[1]。')).toBe('現行は紙である。');
    expect(stripCitationMarks('現行は紙である [1] です。')).toBe('現行は紙である です。');
  });

  it('入れ子の字下げを残し、出典だけの行を捨てる', () => {
    const text = [
      '- **総合評価**',
      '  - 適合している[1]。',
      '  - 【出典】[1], [9]',
      '',
      '- **体制**',
      '  - CSIRTを置く。',
      '  - 【出典】[2], [5], [6]',
    ].join('\n');
    expect(stripCitationMarks(text)).toBe(
      ['- **総合評価**', '  - 適合している。', '', '- **体制**', '  - CSIRTを置く。'].join('\n'),
    );
  });
});
