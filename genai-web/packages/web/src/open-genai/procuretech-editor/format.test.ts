import { describe, expect, it } from 'vitest';
import { baseName, dirOf, formatBytes } from './format';

describe('procuretech-editor/format', () => {
  describe('formatBytes', () => {
    it('0 以下は "0 B"', () => {
      expect(formatBytes(0)).toBe('0 B');
      expect(formatBytes(-10)).toBe('0 B');
      expect(formatBytes(Number.NaN)).toBe('0 B');
    });

    it('B 単位は整数のまま', () => {
      expect(formatBytes(512)).toBe('512 B');
    });

    it('KB/MB は適切に丸める', () => {
      expect(formatBytes(1024)).toBe('1 KB');
      expect(formatBytes(1536)).toBe('1.5 KB');
      expect(formatBytes(1024 * 1024)).toBe('1 MB');
      expect(formatBytes(1024 * 1024 * 2.5)).toBe('2.5 MB');
    });

    it('10 以上は整数に丸める', () => {
      expect(formatBytes(15 * 1024)).toBe('15 KB');
    });
  });

  describe('dirOf', () => {
    it('親ディレクトリを返す', () => {
      expect(dirOf('a/b/c.md')).toBe('a/b');
    });
    it('ルート直下は空文字', () => {
      expect(dirOf('c.md')).toBe('');
    });
  });

  describe('baseName', () => {
    it('ファイル名部分を返す', () => {
      expect(baseName('a/b/c.md')).toBe('c.md');
      expect(baseName('c.md')).toBe('c.md');
    });
  });
});
