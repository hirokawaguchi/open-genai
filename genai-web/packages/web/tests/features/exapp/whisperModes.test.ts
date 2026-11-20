import { availableWhisperModes } from '@/features/exapp/whisperModes';

describe('availableWhisperModes', () => {
  it('ローカルだけなら選択肢は1つ', () => {
    const modes = availableWhisperModes({ cloud: false, live: false });
    expect(modes.map((mode) => mode.id)).toEqual(['local']);
  });

  it('有効な方式だけを、決まった名前で出す', () => {
    const modes = availableWhisperModes({ cloud: true, live: true });
    expect(modes.map((mode) => mode.label)).toEqual([
      'ファイルから（ローカル処理）',
      'ファイルから（クラウド処理）',
      'マイクから（リアルタイム処理）',
    ]);
  });
});
