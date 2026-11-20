export type WhisperModeId = 'local' | 'cloud' | 'live';

export const WHISPER_MODES: { id: WhisperModeId; label: string }[] = [
  { id: 'local', label: 'ファイルから（ローカル処理）' },
  { id: 'cloud', label: 'ファイルから（クラウド処理）' },
  { id: 'live', label: 'マイクから（リアルタイム処理）' },
];

/** ローカルは常に出す。クラウドとマイクは有効なときだけ。 */
export const availableWhisperModes = (flags: { cloud: boolean; live: boolean }) =>
  WHISPER_MODES.filter((mode) => {
    if (mode.id === 'cloud') {
      return flags.cloud;
    }
    if (mode.id === 'live') {
      return flags.live;
    }
    return true;
  });
