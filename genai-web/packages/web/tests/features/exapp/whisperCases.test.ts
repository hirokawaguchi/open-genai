import { describe, expect, it } from 'vitest';
import { defaultWhisperCaseTitle, whisperCaseTitle, whisperInputModeLabel } from '@/features/exapp/whisperCases';

describe('whisperCaseTitle', () => {
  it('prefers the name given when the case was created', () => {
    expect(whisperCaseTitle({ caseTitle: ' 朝会 ', files: [] }, '0')).toBe('朝会');
  });

  it('uses the attached filename when the case has no name', () => {
    expect(
      whisperCaseTitle(
        { files: [{ key: 'audio', files: [{ filename: 'meeting.mp3', content: '' }] }] },
        '0',
      ),
    ).toBe('meeting.mp3');
  });

  it('labels a microphone job with the time', () => {
    const title = whisperCaseTitle({ source: 'microphone' }, String(Date.UTC(2026, 10, 20, 1, 5)));
    expect(title.startsWith('マイク ')).toBe(true);
  });
});

describe('whisperInputModeLabel', () => {
  it('names the three ways', () => {
    expect(whisperInputModeLabel({ source: 'microphone' })).toBe('マイクから（リアルタイム処理）');
    expect(whisperInputModeLabel({ engine: 'cloud' })).toBe('ファイルから（クラウド処理）');
    expect(whisperInputModeLabel({})).toBe('ファイルから（ローカル処理）');
  });
});

describe('defaultWhisperCaseTitle', () => {
  it('includes the date', () => {
    expect(defaultWhisperCaseTitle(new Date(2026, 10, 20, 9, 5))).toBe('文字起こし 2026-11-20 09:05');
  });
});
