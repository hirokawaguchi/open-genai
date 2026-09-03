import { describe, expect, it } from 'vitest';
import {
  baseName,
  dirOf,
  extractImageSources,
  formatBytes,
  rewriteImageSources,
} from './format';

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

  describe('extractImageSources', () => {
    it('相対パス画像 src を重複なく取り出す', () => {
      const md = '![a](images/a.png)\n\n![b](図/b.jpg "title")\n\n![again](images/a.png)';
      expect(extractImageSources(md).sort()).toEqual(['images/a.png', '図/b.jpg'].sort());
    });
    it('外部 URL・data URI・絶対パスは除外する', () => {
      const md =
        '![h](https://x/y.png) ![d](data:image/png;base64,AAA) ![abs](/files/z.png) ![rel](images/r.png)';
      expect(extractImageSources(md)).toEqual(['images/r.png']);
    });
  });

  describe('rewriteImageSources', () => {
    it('マップにある相対パスのみ URL へ置換し、title/alt を保持する', () => {
      const md = '![図1](図/b.jpg "キャプション") と ![x](images/none.png)';
      const out = rewriteImageSources(md, { '図/b.jpg': 'https://s3/signed' });
      expect(out).toBe('![図1](https://s3/signed "キャプション") と ![x](images/none.png)');
    });
    it('外部 URL は書き換えない', () => {
      const md = '![h](https://x/y.png)';
      expect(rewriteImageSources(md, { 'https://x/y.png': 'nope' })).toBe(md);
    });
  });
});
