/** 制御テキストと画面のバイナリを一つの HTTP ボディに載せる。 */

export const FRAME_TEXT = 1;
export const FRAME_BINARY = 2;
const HEADER = 5;
const MAX_FRAME = 1024 * 1024;

export type BrowserFrame = { kind: number; payload: Uint8Array };

export const encodeFrames = (frames: BrowserFrame[]): Uint8Array => {
  const size = frames.reduce((sum, frame) => sum + HEADER + frame.payload.byteLength, 0);
  const out = new Uint8Array(size);
  let offset = 0;
  for (const frame of frames) {
    if (
      (frame.kind !== FRAME_TEXT && frame.kind !== FRAME_BINARY) ||
      frame.payload.byteLength > MAX_FRAME
    ) {
      throw new Error('frame');
    }
    out[offset] = frame.kind;
    const length = frame.payload.byteLength;
    out[offset + 1] = (length >>> 24) & 0xff;
    out[offset + 2] = (length >>> 16) & 0xff;
    out[offset + 3] = (length >>> 8) & 0xff;
    out[offset + 4] = length & 0xff;
    out.set(frame.payload, offset + HEADER);
    offset += HEADER + length;
  }
  return out;
};

export const decodeFrames = (data: Uint8Array): BrowserFrame[] => {
  const frames: BrowserFrame[] = [];
  let offset = 0;
  while (offset < data.byteLength) {
    if (offset + HEADER > data.byteLength) {
      throw new Error('frame');
    }
    const kind = data[offset] ?? 0;
    const length =
      ((data[offset + 1] ?? 0) << 24) |
      ((data[offset + 2] ?? 0) << 16) |
      ((data[offset + 3] ?? 0) << 8) |
      (data[offset + 4] ?? 0);
    offset += HEADER;
    if (
      (kind !== FRAME_TEXT && kind !== FRAME_BINARY) ||
      length > MAX_FRAME ||
      offset + length > data.byteLength
    ) {
      throw new Error('frame');
    }
    frames.push({ kind, payload: data.slice(offset, offset + length) });
    offset += length;
  }
  return frames;
};
