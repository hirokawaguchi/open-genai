export type WhisperDraft = {
  id: string;
  title: string;
  createdAt: string;
  /** ファイル送信中。画面を離れても一覧に処理中と出す。 */
  phase?: 'sending' | 'error';
  mode?: 'local' | 'cloud';
  notice?: string;
};

const pad = (value: number) => String(value).padStart(2, '0');

export const defaultWhisperCaseTitle = (now = new Date()) =>
  `文字起こし ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;

const whenOf = (createdDate: string) => {
  const date = new Date(Number(createdDate));
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

export const whisperInputFilename = (inputs: Record<string, unknown>): string => {
  const files = inputs.files;
  if (!Array.isArray(files)) {
    return '';
  }
  for (const entry of files) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }
    const inner = (entry as { files?: unknown }).files;
    if (!Array.isArray(inner)) {
      continue;
    }
    for (const file of inner) {
      if (!file || typeof file !== 'object') {
        continue;
      }
      const name = (file as { filename?: unknown }).filename;
      if (typeof name === 'string' && name.trim()) {
        return name.trim();
      }
    }
  }
  return '';
};

/** 一覧に出す名前。付けた案件名、無ければファイル名、それも無ければ日時。 */
export const whisperCaseTitle = (inputs: Record<string, unknown>, createdDate: string) => {
  const named = typeof inputs.caseTitle === 'string' ? inputs.caseTitle.trim() : '';
  if (named) {
    return named;
  }
  const filename = whisperInputFilename(inputs);
  if (filename) {
    return filename;
  }
  const when = whenOf(createdDate);
  if (inputs.source === 'microphone') {
    return when ? `マイク ${when}` : 'マイク';
  }
  return when ? `文字起こし ${when}` : '文字起こし';
};

export const whisperInputModeLabel = (inputs: Record<string, unknown>) => {
  if (inputs.source === 'microphone') {
    return 'マイクから（リアルタイム処理）';
  }
  if (inputs.engine === 'cloud') {
    return 'ファイルから（クラウド処理）';
  }
  return 'ファイルから（ローカル処理）';
};
