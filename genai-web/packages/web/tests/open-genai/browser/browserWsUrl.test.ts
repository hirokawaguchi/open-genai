import { describe, expect, it } from 'vitest';
import { browserWsUrl } from '@/open-genai/browser/browserWsUrl';

describe('browserWsUrl', () => {
  it('converts an absolute http API endpoint to ws', () => {
    expect(browserWsUrl('http://localhost/api')).toBe('ws://localhost/api/browser/ws');
  });

  it('converts an absolute https API endpoint to wss', () => {
    expect(browserWsUrl('https://example.jp/api')).toBe('wss://example.jp/api/browser/ws');
  });

  it('uses the current origin for a relative API endpoint', () => {
    expect(browserWsUrl('/api', { protocol: 'https:', host: 'app.example.jp' })).toBe(
      'wss://app.example.jp/api/browser/ws',
    );
  });

  it('builds the audio socket on the same origin', () => {
    expect(browserWsUrl('https://example.jp/api', window.location, '/browser/audio')).toBe(
      'wss://example.jp/api/browser/audio',
    );
  });
});
