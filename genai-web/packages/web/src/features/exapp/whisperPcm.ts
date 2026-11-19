export const TARGET_RATE = 24000;

export const resampleLinear = (
  input: Float32Array,
  inRate: number,
  outRate: number,
): Float32Array => {
  if (input.length === 0 || inRate <= 0 || outRate <= 0) {
    return new Float32Array();
  }
  if (inRate === outRate) {
    return input;
  }
  const ratio = inRate / outRate;
  const length = Math.max(1, Math.round(input.length / ratio));
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const pos = i * ratio;
    const i0 = Math.min(Math.floor(pos), input.length - 1);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const t = pos - i0;
    out[i] = input[i0] * (1 - t) + input[i1] * t;
  }
  return out;
};

export const floatToPcm16 = (samples: Float32Array): Uint8Array => {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return bytes;
};

export const bytesToBase64 = (bytes: Uint8Array): string => {
  let binary = '';
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step));
  }
  return btoa(binary);
};

export const pcmBase64FromFloat = (input: Float32Array, inRate: number): string =>
  bytesToBase64(floatToPcm16(resampleLinear(input, inRate, TARGET_RATE)));
