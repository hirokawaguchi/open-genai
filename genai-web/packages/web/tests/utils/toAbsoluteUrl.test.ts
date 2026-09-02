import { describe, expect, it } from 'vitest';
import { toAbsoluteUrl } from '@/utils/toAbsoluteUrl';

describe('toAbsoluteUrl', () => {
  it('すでに絶対 URL ならそのまま', () => {
    expect(toAbsoluteUrl('http://example.test/public/e/abc', 'http://other')).toBe(
      'http://example.test/public/e/abc',
    );
  });

  it('相対パスにオリジンを付ける', () => {
    expect(toAbsoluteUrl('/public/e/abc', 'http://example.test')).toBe(
      'http://example.test/public/e/abc',
    );
  });
});
