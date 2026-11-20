// 180MB は端末からサーバーへ送る JSON の上限。動画は音声だけを送るので、
// 判定する大きさはファイル形式で変わる。
export const WHISPER_UPLOAD_LIMIT_BYTES = 180 * 1024 * 1024;

export const AUDIO_TOO_LARGE =
  '音声ファイルの目安は 180MB までです。分割してから読み込んでください。';
export const EXTRACTED_TOO_LARGE =
  '取り出した音声が 180MB を超えています。ファイルを分割してから読み込んでください。';
export const WHOLE_TOO_LARGE =
  'この形式は音声だけを取り出せないため、ファイルの目安は 180MB までです。音声を取り出してから、または分割してから読み込んでください。';
export const NO_AUDIO_TRACK = 'このファイルには音声トラックがありません。';

const VIDEO_EXTENSIONS = new Set([
  'mp4',
  'm4v',
  'mov',
  'webm',
  'mkv',
  'avi',
  'mpeg',
  'mpg',
  '3gp',
  'wmv',
]);

export type WhisperFileKind = 'video' | 'audio';

export function whisperFileKind(file: { type: string; name: string }): WhisperFileKind {
  const type = file.type.toLowerCase();
  if (type.startsWith('video/')) {
    return 'video';
  }
  if (type.startsWith('audio/')) {
    return 'audio';
  }
  const dot = file.name.lastIndexOf('.');
  const ext = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : '';
  return VIDEO_EXTENSIONS.has(ext) ? 'video' : 'audio';
}

export type WhisperExtraction =
  | 'not-video'
  | 'no-video-track'
  | 'no-audio'
  | 'failed'
  | { bytes: number };

export type WhisperUploadDecision = { send: 'original' | 'extracted' } | { error: string };

// 取り出した音声が上限を超えても、元ファイルが収まるなら元のまま送る。
export function decideWhisperPayload(input: {
  originalBytes: number;
  extraction: WhisperExtraction;
}): WhisperUploadDecision {
  const { originalBytes, extraction } = input;
  if (extraction === 'no-audio') {
    return { error: NO_AUDIO_TRACK };
  }
  if (extraction === 'failed') {
    if (originalBytes > WHISPER_UPLOAD_LIMIT_BYTES) {
      return { error: WHOLE_TOO_LARGE };
    }
    return { send: 'original' };
  }
  if (extraction === 'not-video' || extraction === 'no-video-track') {
    if (originalBytes > WHISPER_UPLOAD_LIMIT_BYTES) {
      return { error: AUDIO_TOO_LARGE };
    }
    return { send: 'original' };
  }
  if (extraction.bytes <= 0) {
    return { error: NO_AUDIO_TRACK };
  }
  if (extraction.bytes <= WHISPER_UPLOAD_LIMIT_BYTES) {
    return { send: 'extracted' };
  }
  if (originalBytes <= WHISPER_UPLOAD_LIMIT_BYTES) {
    return { send: 'original' };
  }
  return { error: EXTRACTED_TOO_LARGE };
}

export function rejectOversizedAudio(file: {
  type: string;
  name: string;
  size: number;
}): string | null {
  if (whisperFileKind(file) === 'video') {
    return null;
  }
  if (file.size > WHISPER_UPLOAD_LIMIT_BYTES) {
    return AUDIO_TOO_LARGE;
  }
  return null;
}
