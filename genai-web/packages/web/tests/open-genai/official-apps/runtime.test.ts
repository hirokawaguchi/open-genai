import { describe, expect, it } from 'vitest';
import {
  filterRunningOfficialOptions,
  officialAppRuntimeKind,
} from '@/open-genai/official-apps/runtime';

const OPTIONS = [
  { id: 'chat', label: 'チャット' },
  { id: 'image', label: '画像を生成' },
  { id: 'chosei', label: '日程調整' },
  { id: 'ssh', label: 'SSH 端末' },
];

describe('filterRunningOfficialOptions', () => {
  it('hides optional apps until runtime is loaded', () => {
    expect(filterRunningOfficialOptions(OPTIONS, undefined).map((o) => o.id)).toEqual([
      'chat',
    ]);
  });

  it('keeps only running official apps', () => {
    expect(
      filterRunningOfficialOptions(OPTIONS, ['chat', 'chosei', 'unknown']).map((o) => o.id),
    ).toEqual(['chat', 'chosei']);
  });
});

describe('officialAppRuntimeKind', () => {
  it('marks unknown until runtime is loaded', () => {
    expect(officialAppRuntimeKind('ssh', undefined)).toBe('unknown');
  });

  it('distinguishes running from stopped', () => {
    expect(officialAppRuntimeKind('chat', ['chat'])).toBe('running');
    expect(officialAppRuntimeKind('ssh', ['chat'])).toBe('stopped');
  });

  it('treats knowledge search as always on', () => {
    expect(officialAppRuntimeKind('rag', [])).toBe('running');
    expect(officialAppRuntimeKind('rag', undefined)).toBe('running');
  });
});
