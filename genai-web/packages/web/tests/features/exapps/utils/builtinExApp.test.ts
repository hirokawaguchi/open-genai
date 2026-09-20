import { describe, expect, it } from 'vitest';
import {
  builtinRouteOf,
  isBuiltinConfig,
  isCatalogListed,
  isKnowledgeSearchApp,
} from '@/features/exapps/utils/builtinExApp';

describe('builtinExApp', () => {
  it('detects knowledge search apps', () => {
    expect(isKnowledgeSearchApp({ exAppId: 'rag' })).toBe(true);
    expect(
      isKnowledgeSearchApp({
        exAppId: 'team-search',
        config: '{"dynamic_schema":true,"rag_role":"search"}',
      }),
    ).toBe(true);
    expect(isKnowledgeSearchApp({ exAppId: 'knowledge' })).toBe(false);
  });

  it('parses builtin config', () => {
    expect(isBuiltinConfig('{"builtin":true,"route":"/chat"}')).toBe(true);
    expect(isBuiltinConfig('{"dynamic_schema":true}')).toBe(false);
    expect(isBuiltinConfig('')).toBe(false);
  });

  it('reads builtin route', () => {
    expect(builtinRouteOf('{"builtin":true,"route":"/diagram"}')).toBe('/diagram');
    expect(builtinRouteOf('{"builtin":true,"route":"diagram"}')).toBeNull();
  });

  it('hides draft catalog apps after load', () => {
    const apps = [{ exAppId: 'diagram', status: 'draft' as const }];
    expect(isCatalogListed('diagram', apps, true)).toBe(false);
    expect(isCatalogListed('chat', apps, true)).toBe(false);
    expect(isCatalogListed('prompt', apps, true)).toBe(false);
  });

  it('hides apps missing from a loaded catalog', () => {
    const apps = [{ exAppId: 'chat', status: 'published' as const }];
    expect(isCatalogListed('image', apps, true)).toBe(false);
    expect(isCatalogListed('chat', apps, true)).toBe(true);
  });

  it('shows defaults before catalog is loaded', () => {
    expect(isCatalogListed('diagram', [], false)).toBe(true);
    expect(isCatalogListed('prompt', [], false)).toBe(true);
  });

  it('shows published catalog apps', () => {
    const apps = [
      { exAppId: 'diagram', status: 'published' as const },
      { exAppId: 'prompt', status: 'published' as const },
    ];
    expect(isCatalogListed('diagram', apps, true)).toBe(true);
    expect(isCatalogListed('prompt', apps, true)).toBe(true);
  });
});
