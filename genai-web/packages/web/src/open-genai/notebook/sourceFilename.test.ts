import { describe, expect, it } from 'vitest';
import { sourceFilename } from './NotebookSourceHandoff';

describe('sourceFilename', () => {
  it('種類のあとに本文の先頭を付ける', () => {
    expect(sourceFilename('翻訳.md', '住民サービスを向上させるため、手続を簡単にします。')).toBe(
      '翻訳-住民サービスを向上させるため、手続を簡単.md',
    );
  });

  it('見出し記号と改行を名前から外す', () => {
    expect(sourceFilename('チャット.md', '# 概要\n\n紙の申請が残っている。')).toBe(
      'チャット-概要 紙の申請が残っている.md',
    );
  });

  it('本文が空なら種類だけの名前にする', () => {
    expect(sourceFilename('文字起こし.md', '```\n\n```')).toBe('文字起こし.md');
  });

  it('画像は拡張子を残す', () => {
    expect(sourceFilename('画像.png', '窓口の案内図')).toBe('画像-窓口の案内図.png');
  });
});
