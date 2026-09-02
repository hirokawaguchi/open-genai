import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MODEL_ID_STORAGE_KEY,
  availableTextModelIds,
  resolveSelectedModelId,
} from '@/models';

describe('resolveSelectedModelId', () => {
  const store: Record<string, string> = {};

  beforeEach(() => {
    for (const key of Object.keys(store)) {
      delete store[key];
    }
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => {
        store[key] = value;
      },
      removeItem: (key: string) => {
        delete store[key];
      },
      clear: () => {
        for (const key of Object.keys(store)) {
          delete store[key];
        }
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('保存が無ければ有効な先頭モデルを返す', () => {
    const ids = availableTextModelIds();
    expect(resolveSelectedModelId()).toBe(ids[0]);
  });

  it('有効な保存済み ID はそのまま返す', () => {
    const ids = availableTextModelIds();
    if (ids.length === 0) {
      expect(resolveSelectedModelId()).toBeUndefined();
      return;
    }
    store[MODEL_ID_STORAGE_KEY] = ids[0];
    expect(resolveSelectedModelId()).toBe(ids[0]);
  });

  it('無効な保存済み ID は有効な先頭へ書き戻す', () => {
    const ids = availableTextModelIds();
    if (ids.length === 0) {
      return;
    }
    store[MODEL_ID_STORAGE_KEY] = '__no_such_model__';
    expect(resolveSelectedModelId()).toBe(ids[0]);
    expect(store[MODEL_ID_STORAGE_KEY]).toBe(ids[0]);
  });
});
