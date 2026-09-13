import { describe, expect, it } from 'vitest';
import { encodePty } from '@/open-genai/ssh/encodePty';

describe('encodePty', () => {
  it('encodes ASCII as-is', () => {
    expect(Array.from(encodePty('ab'))).toEqual([0x61, 0x62]);
  });

  it('encodes Japanese as UTF-8', () => {
    expect(Array.from(encodePty('あ'))).toEqual([0xe3, 0x81, 0x82]);
  });
});
