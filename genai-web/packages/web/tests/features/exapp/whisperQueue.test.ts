import { firstFormFile, whisperQueueParams } from '@/features/exapp/whisperQueue';

describe('whisperQueue', () => {
  it('uses the browser duration when the file has one', () => {
    const file = new File(['abc'], 'meeting.mp3', { type: 'audio/mpeg' });
    expect(whisperQueueParams(file, 49 * 60)).toEqual({ audioSeconds: 49 * 60 });
  });

  it('falls back to the byte size when duration is unknown', () => {
    const file = new File(['abcd'], 'meeting.mp3', { type: 'audio/mpeg' });
    expect(whisperQueueParams(file, null)).toEqual({ nbytes: file.size });
  });

  it('reads the first attached file from the form', () => {
    const file = new File(['a'], 'a.mp3');
    expect(firstFormFile({ language: 'ja', audio: [file] })).toBe(file);
    expect(firstFormFile({ language: 'ja' })).toBeNull();
  });
});
