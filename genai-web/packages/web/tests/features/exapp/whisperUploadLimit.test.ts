import {
  AUDIO_TOO_LARGE,
  decideWhisperPayload,
  EXTRACTED_TOO_LARGE,
  NO_AUDIO_TRACK,
  rejectOversizedAudio,
  WHISPER_UPLOAD_LIMIT_BYTES,
  WHOLE_TOO_LARGE,
  whisperFileKind,
} from '@/features/exapp/whisperUploadLimit';

const OVER = WHISPER_UPLOAD_LIMIT_BYTES + 1;

describe('whisperUploadLimit', () => {
  it('treats video containers as extractable and audio files as themselves', () => {
    expect(whisperFileKind({ type: 'video/mp4', name: 'meeting.mp4' })).toBe('video');
    expect(whisperFileKind({ type: '', name: 'meeting.mkv' })).toBe('video');
    expect(whisperFileKind({ type: 'audio/mp4', name: 'meeting.m4a' })).toBe('audio');
    expect(whisperFileKind({ type: '', name: 'meeting.mp3' })).toBe('audio');
  });

  it('accepts a video larger than 180MB and rejects an audio file of that size', () => {
    expect(rejectOversizedAudio({ type: 'video/mp4', name: 'meeting.mp4', size: OVER })).toBeNull();
    expect(rejectOversizedAudio({ type: 'audio/mpeg', name: 'meeting.mp3', size: OVER })).toBe(
      AUDIO_TOO_LARGE,
    );
    expect(rejectOversizedAudio({ type: '', name: 'clip.avi', size: OVER })).toBeNull();
  });

  it('sends the extracted audio when it fits, even if the video does not', () => {
    expect(
      decideWhisperPayload({ originalBytes: OVER, extraction: { bytes: 20 * 1024 * 1024 } }),
    ).toEqual({
      send: 'extracted',
    });
  });

  it('refuses when the extracted audio itself exceeds 180MB', () => {
    expect(decideWhisperPayload({ originalBytes: OVER, extraction: { bytes: OVER } })).toEqual({
      error: EXTRACTED_TOO_LARGE,
    });
  });

  it('keeps the original when the audio cannot be extracted and the file fits', () => {
    expect(decideWhisperPayload({ originalBytes: 1024, extraction: 'failed' })).toEqual({
      send: 'original',
    });
    expect(decideWhisperPayload({ originalBytes: 1024, extraction: 'no-video-track' })).toEqual({
      send: 'original',
    });
  });

  it('refuses a file that cannot be stripped and is over 180MB', () => {
    expect(decideWhisperPayload({ originalBytes: OVER, extraction: 'failed' })).toEqual({
      error: WHOLE_TOO_LARGE,
    });
  });

  it('refuses a video that has no audio track', () => {
    expect(decideWhisperPayload({ originalBytes: 1024, extraction: 'no-audio' })).toEqual({
      error: NO_AUDIO_TRACK,
    });
  });

  it('sends the original when stripping would make a fitting file larger than 180MB', () => {
    expect(decideWhisperPayload({ originalBytes: 1024, extraction: { bytes: OVER } })).toEqual({
      send: 'original',
    });
  });
});
