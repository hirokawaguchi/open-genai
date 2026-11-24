export const PLAYBACK_RATE = 48000;
export const MIC_RATE = 48000;
export const MIC_FRAME = 960;

export const stereoS16ToFloat = (
  data: ArrayBuffer,
): { left: Float32Array; right: Float32Array } | null => {
  const view = new DataView(data);
  const frames = Math.floor(view.byteLength / 4);
  if (frames < 1) {
    return null;
  }
  const left = new Float32Array(frames);
  const right = new Float32Array(frames);
  for (let i = 0; i < frames; i++) {
    left[i] = view.getInt16(i * 4, true) / 32768;
    right[i] = view.getInt16(i * 4 + 2, true) / 32768;
  }
  return { left, right };
};

export const resampleLinear = (
  input: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array => {
  if (fromRate === toRate || input.length === 0) {
    return input;
  }
  const outLength = Math.max(1, Math.round((input.length * toRate) / fromRate));
  const out = new Float32Array(outLength);
  const scale = fromRate / toRate;
  for (let i = 0; i < outLength; i++) {
    const pos = i * scale;
    const index = Math.floor(pos);
    const next = Math.min(index + 1, input.length - 1);
    const mix = pos - index;
    out[i] = input[index] * (1 - mix) + input[next] * mix;
  }
  return out;
};

const floatsToS16 = (samples: number[]): ArrayBuffer => {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i] ?? 0));
    view.setInt16(i * 2, Math.round(clamped * 32767), true);
  }
  return buffer;
};

/** マイクのサンプルを 48kHz・20ms の s16le に揃える。 */
export class MicFramer {
  private pending: number[] = [];

  push(samples: Float32Array, sampleRate: number): ArrayBuffer[] {
    const resampled = resampleLinear(samples, sampleRate, MIC_RATE);
    for (const sample of resampled) {
      this.pending.push(sample);
    }
    if (this.pending.length > MIC_RATE) {
      this.pending.splice(0, this.pending.length - MIC_RATE);
    }
    const frames: ArrayBuffer[] = [];
    while (this.pending.length >= MIC_FRAME) {
      frames.push(floatsToS16(this.pending.splice(0, MIC_FRAME)));
    }
    return frames;
  }
}
