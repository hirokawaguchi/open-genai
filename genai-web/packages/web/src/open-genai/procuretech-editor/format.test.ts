import { describe, expect, it } from 'vitest';
import {
  baseName,
  composeFormatOf,
  dirOf,
  extractImageSources,
  formatBytes,
  isVisualComposeFormat,
  markdownImage,
  resolveProjectImagePath,
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
    it('空白・山括弧・%20 のファイル名を取り出す', () => {
      const md = [
        '![a](スクリーンショット 1.png)',
        '![b](<images/図 2.png>)',
        '![c](images/a%20b.png)',
      ].join('\n');
      expect(extractImageSources(md).sort()).toEqual(
        ['images/a b.png', 'images/図 2.png', 'スクリーンショット 1.png'].sort(),
      );
    });
  });

  describe('resolveProjectImagePath', () => {
    const paths = ['images/a.png', 'docs/図 1.png'];
    it('案件ルートからのパスをそのまま解決する', () => {
      expect(resolveProjectImagePath('images/a.png', '手順.md', paths)).toBe('images/a.png');
    });
    it('開いている Markdown からの相対パスを解決する', () => {
      expect(resolveProjectImagePath('./図 1.png', 'docs/手順.md', paths)).toBe('docs/図 1.png');
    });
    it('無いパスは null', () => {
      expect(resolveProjectImagePath('missing.png', '手順.md', paths)).toBeNull();
    });
  });

  describe('markdownImage', () => {
    it('空白や括弧を含むパスは山括弧で囲む', () => {
      expect(markdownImage('図', 'images/a.png')).toBe('![図](images/a.png)');
      expect(markdownImage('図', 'スクリーンショット 1.png')).toBe(
        '![図](<スクリーンショット 1.png>)',
      );
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
    it('空白を含むパスも URL へ置換する', () => {
      const md = '![図](スクリーンショット 1.png)';
      expect(rewriteImageSources(md, { 'スクリーンショット 1.png': 'https://s3/a' })).toBe(
        '![図](https://s3/a)',
      );
    });
  });

  describe('composeFormatOf', () => {
    it('未指定は docx', () => {
      expect(composeFormatOf({})).toBe('docx');
    });
    it('指定があればそれを返す', () => {
      expect(composeFormatOf({ format: 'html' })).toBe('html');
    });
  });

  describe('isVisualComposeFormat', () => {
    it('docx / html / pptx は視覚形式', () => {
      expect(isVisualComposeFormat('docx')).toBe(true);
      expect(isVisualComposeFormat('html')).toBe(true);
      expect(isVisualComposeFormat('md')).toBe(false);
      expect(isVisualComposeFormat('txt')).toBe(false);
    });
  });
});
