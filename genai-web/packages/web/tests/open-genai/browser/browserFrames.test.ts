import { describe, expect, it } from 'vitest';
import { FRAME_BINARY, FRAME_TEXT, decodeFrames, encodeFrames } from '@/open-genai/browser/browserFrames';

describe('browserFrames', () => {
  it('round-trips text and binary frames', () => {
    const encoded = encodeFrames([
      { kind: FRAME_TEXT, payload: new TextEncoder().encode('準備') },
      { kind: FRAME_BINARY, payload: new Uint8Array([0, 1]) },
    ]);
    const frames = decodeFrames(encoded);
    expect(frames.map((frame) => frame.kind)).toEqual([FRAME_TEXT, FRAME_BINARY]);
    expect(new TextDecoder().decode(frames[0]?.payload)).toBe('準備');
    expect(Array.from(frames[1]?.payload ?? [])).toEqual([0, 1]);
  });

  it('rejects a truncated frame', () => {
    expect(() => decodeFrames(new Uint8Array([FRAME_TEXT, 0, 0, 0, 2, 1]))).toThrow('frame');
  });
});
