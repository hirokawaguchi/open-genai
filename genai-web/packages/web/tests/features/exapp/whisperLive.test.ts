import { describe, expect, it } from 'vitest';
import { whisperLiveUrl } from '@/features/exapp/whisperLiveUrl';
import { pcmBase64FromFloat, resampleLinear } from '@/features/exapp/whisperPcm';
import { applyLiveMessage, liveTranscript } from '@/features/exapp/whisperTranscript';

describe('whisperLiveUrl', () => {
  it('converts an absolute http API endpoint to ws', () => {
    expect(whisperLiveUrl('http://localhost/api')).toBe('ws://localhost/api/whisper/live');
  });

  it('converts an absolute https API endpoint to wss', () => {
    expect(whisperLiveUrl('https://genai.example.lg.jp/api')).toBe(
      'wss://genai.example.lg.jp/api/whisper/live',
    );
  });

  it('uses the current origin for a relative API endpoint', () => {
    expect(whisperLiveUrl('/api', { protocol: 'https:', host: 'app.example.lg.jp' })).toBe(
      'wss://app.example.lg.jp/api/whisper/live',
    );
  });
});

describe('whisperPcm', () => {
  it('downsamples 48 kHz audio to 24 kHz', () => {
    const input = new Float32Array([0, 0.5, 1, 0.5]);
    expect(resampleLinear(input, 48000, 24000)).toHaveLength(2);
  });

  it('encodes PCM16 as base64', () => {
    const encoded = pcmBase64FromFloat(new Float32Array([0, 1, -1]), 24000);
    expect(encoded.length).toBeGreaterThan(0);
    expect(atob(encoded).length).toBe(6);
  });
});

describe('whisperTranscript', () => {
  it('replaces a partial turn with the final transcript', () => {
    const partial = applyLiveMessage([], {
      type: 'delta',
      itemId: 'item_1',
      text: 'こんに',
    });
    const extended = applyLiveMessage(partial, {
      type: 'delta',
      itemId: 'item_1',
      text: 'こんにちは',
    });
    const done = applyLiveMessage(extended, {
      type: 'transcript',
      itemId: 'item_1',
      text: 'こんにちは',
    });
    expect(liveTranscript(done)).toBe('こんにちは');
  });
});
