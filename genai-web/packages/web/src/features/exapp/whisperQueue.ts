export type WhisperQueueView = {
  ahead: number;
  position: number;
  startInSeconds: number;
  ownSeconds: number;
  finishInSeconds: number;
  limitSeconds: number;
  canStart: boolean;
  message: string;
};

/** フォーム入力から、最初の添付ファイルを取り出す。 */
export const firstFormFile = (data: Record<string, unknown>): File | null => {
  for (const value of Object.values(data)) {
    if (typeof FileList !== 'undefined' && value instanceof FileList && value.length > 0) {
      return value[0] ?? null;
    }
    if (Array.isArray(value) && value[0] instanceof File) {
      return value[0];
    }
  }
  return null;
};

/** ブラウザが再生時間を読めたときだけ秒を返す。読めなければ null。 */
export const readAudioDurationSeconds = (file: File): Promise<number | null> => {
  if (typeof document === 'undefined' || typeof URL === 'undefined') {
    return Promise.resolve(null);
  }
  const url = URL.createObjectURL(file);
  return new Promise((resolve) => {
    const audio = document.createElement('audio');
    audio.preload = 'metadata';
    const finish = (seconds: number | null) => {
      URL.revokeObjectURL(url);
      resolve(seconds);
    };
    audio.onloadedmetadata = () => {
      const seconds = audio.duration;
      finish(Number.isFinite(seconds) && seconds > 0 ? seconds : null);
    };
    audio.onerror = () => finish(null);
    audio.src = url;
  });
};

export const whisperQueueParams = (
  file: File,
  audioSeconds: number | null,
): { audioSeconds: number } | { nbytes: number } => {
  if (audioSeconds !== null && audioSeconds > 0) {
    return { audioSeconds: Math.round(audioSeconds) };
  }
  return { nbytes: file.size };
};
