import {
  firstFormFile,
  processEstimateLabel,
  whisperQueueParams,
} from '@/features/exapp/whisperQueue';

describe('whisperQueue', () => {
  it('uses the browser duration when the file has one', () => {
    const file = new File(['abc'], 'meeting.mp3', { type: 'audio/mpeg' });
    expect(whisperQueueParams(file, 49 * 60)).toEqual({ audioSeconds: 49 * 60 });
  });

  it('falls back to the byte size when duration is unknown', () => {
    const file = new File(['abcd'], 'meeting.mp3', { type: 'audio/mpeg' });
    expect(whisperQueueParams(file, null)).toEqual({ nbytes: file.size });
  });

  it('turns the server processing seconds into a minute estimate', () => {
    expect(processEstimateLabel(12 * 60)).toBe('このファイルの処理見込みは約12分です。');
    expect(processEstimateLabel(90)).toBe('このファイルの処理見込みは約2分です。');
    expect(processEstimateLabel(0)).toBe('');
  });

  it('reads the first attached file from the form', () => {
    const file = new File(['a'], 'a.mp3');
    expect(firstFormFile({ language: 'ja', audio: [file] })).toBe(file);
    expect(firstFormFile({ language: 'ja' })).toBeNull();
  });
});
