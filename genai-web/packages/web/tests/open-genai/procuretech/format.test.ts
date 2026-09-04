import { describe, expect, it } from 'vitest';
import { parseDownloadFilename } from '@/open-genai/procuretech/format';

describe('parseDownloadFilename', () => {
  it('falls back when header is missing', () => {
    expect(parseDownloadFilename(null)).toBe('systemplan.xlsx');
    expect(parseDownloadFilename(null, 'x.xlsx')).toBe('x.xlsx');
  });

  it('reads ASCII filename', () => {
    expect(parseDownloadFilename('attachment; filename="systemplan_20260902.xlsx"')).toBe(
      'systemplan_20260902.xlsx',
    );
  });

  it('prefers and decodes RFC5987 UTF-8 filename', () => {
    const encoded = encodeURIComponent('情報化企画書_更新版.xlsx');
    const disposition = `attachment; filename="systemplan.xlsx"; filename*=UTF-8''${encoded}`;
    expect(parseDownloadFilename(disposition)).toBe('情報化企画書_更新版.xlsx');
  });
});
