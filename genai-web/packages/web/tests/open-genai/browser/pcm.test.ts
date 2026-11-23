import { describe, expect, it } from 'vitest';
import { MicFramer, stereoS16ToFloat } from '@/open-genai/browser/pcm';

describe('stereoS16ToFloat', () => {
  it('splits little-endian stereo samples', () => {
    const bytes = new ArrayBuffer(8);
    const view = new DataView(bytes);
    view.setInt16(0, 16384, true);
    view.setInt16(2, -16384, true);
    view.setInt16(4, 0, true);
    view.setInt16(6, 32767, true);
    const decoded = stereoS16ToFloat(bytes);
    expect(decoded?.left[0]).toBeCloseTo(0.5);
    expect(decoded?.right[0]).toBeCloseTo(-0.5);
    expect(decoded?.left[1]).toBe(0);
    expect(decoded?.right[1]).toBeCloseTo(32767 / 32768);
  });
});

describe('MicFramer', () => {
  it('emits 20ms frames of s16le at 48kHz', () => {
    const framer = new MicFramer();
    const samples = new Float32Array(960);
    samples.fill(1);
    const frames = framer.push(samples, 48000);
    expect(frames).toHaveLength(1);
    const view = new DataView(frames[0] ?? new ArrayBuffer(0));
    expect(view.byteLength).toBe(1920);
    expect(view.getInt16(0, true)).toBe(32767);
    expect(framer.push(new Float32Array(100), 48000)).toHaveLength(0);
  });
});
