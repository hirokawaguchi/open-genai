import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { ALL_FORMATS, BlobSource, Input } from 'mediabunny';
import { prepareWhisperUpload, WhisperUploadError } from '@/features/exapp/whisperAudioExtract';
import { AUDIO_TOO_LARGE, WHISPER_UPLOAD_LIMIT_BYTES } from '@/features/exapp/whisperUploadLimit';

describe('prepareWhisperUpload', () => {
  it('leaves an audio file untouched', async () => {
    const file = new File([new Uint8Array([1, 2, 3])], 'meeting.mp3', { type: 'audio/mpeg' });
    await expect(prepareWhisperUpload(file)).resolves.toBe(file);
  });

  it('refuses an audio file over 180MB', async () => {
    const file = new File([new Uint8Array([1])], 'meeting.mp3', { type: 'audio/mpeg' });
    Object.defineProperty(file, 'size', { value: WHISPER_UPLOAD_LIMIT_BYTES + 1 });
    await expect(prepareWhisperUpload(file)).rejects.toBeInstanceOf(WhisperUploadError);
    await expect(prepareWhisperUpload(file)).rejects.toThrow(AUDIO_TOO_LARGE);
  });

  it('sends only the audio track of an mp4', async () => {
    const bytes = new Uint8Array(
      readFileSync(join(process.cwd(), 'tests/features/exapp/fixtures/tiny-h264.mp4')),
    );
    const file = new File([bytes], 'meeting.mp4', { type: 'video/mp4' });
    const extracted = await prepareWhisperUpload(file);
    expect(extracted).not.toBe(file);
    expect(extracted.name).toBe('meeting.m4a');
    expect(extracted.type).toBe('audio/mp4');
    expect(extracted.size).toBeGreaterThan(0);
    expect(extracted.size).toBeLessThan(file.size);
    const input = new Input({ formats: ALL_FORMATS, source: new BlobSource(extracted) });
    try {
      expect(await input.getPrimaryVideoTrack()).toBeNull();
      expect((await input.getPrimaryAudioTrack())?.codec).toBe('aac');
    } finally {
      input.dispose();
    }
  });
});
