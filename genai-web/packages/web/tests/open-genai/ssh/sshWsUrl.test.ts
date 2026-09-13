import { describe, expect, it } from 'vitest';
import { sshWsUrl } from '@/open-genai/ssh/sshWsUrl';

describe('sshWsUrl', () => {
  it('converts an absolute http API endpoint to ws', () => {
    expect(sshWsUrl('http://localhost/api')).toBe('ws://localhost/api/ssh/ws');
  });

  it('converts an absolute https API endpoint to wss', () => {
    expect(sshWsUrl('https://genai.example.lg.jp/api')).toBe(
      'wss://genai.example.lg.jp/api/ssh/ws',
    );
  });

  it('uses the current origin for a relative API endpoint', () => {
    expect(sshWsUrl('/api', { protocol: 'https:', host: 'app.example.lg.jp' })).toBe(
      'wss://app.example.lg.jp/api/ssh/ws',
    );
  });
});
