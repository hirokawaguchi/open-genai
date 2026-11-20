import { afterEach, describe, expect, it } from 'vitest';
import {
  readWhisperDrafts,
  settleInterruptedWhisperDrafts,
  upsertWhisperDraft,
  writeWhisperDrafts,
} from '@/features/exapp/whisperTransfer';

const teamId = 'team-1';

afterEach(() => {
  sessionStorage.clear();
});

describe('whisper draft transfer status', () => {
  it('keeps a sending case so the list can show it after leaving the screen', () => {
    upsertWhisperDraft(teamId, {
      id: 'case-1',
      title: '朝会',
      createdAt: '2026-11-20T12:00:00.000Z',
      phase: 'sending',
      mode: 'local',
    });
    expect(readWhisperDrafts(teamId)[0]?.phase).toBe('sending');
  });

  it('marks a sending case as an error when the transfer is gone', () => {
    writeWhisperDrafts(teamId, [
      {
        id: 'case-1',
        title: '朝会',
        createdAt: '2026-11-20T12:00:00.000Z',
        phase: 'sending',
        mode: 'cloud',
      },
    ]);
    const next = settleInterruptedWhisperDrafts(teamId);
    expect(next[0]?.phase).toBe('error');
    expect(next[0]?.notice).toContain('中断');
  });
});
