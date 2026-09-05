import { describe, expect, it } from 'vitest';
import { parseEnvStringList } from '../../src/models';

describe('parseEnvStringList', () => {
  it('parses a JSON string array', () => {
    expect(parseEnvStringList('["gpt-4.1","claude-sonnet-4-6"]')).toEqual([
      'gpt-4.1',
      'claude-sonnet-4-6',
    ]);
  });

  it('parses a YAML-stripped list that is not valid JSON', () => {
    expect(parseEnvStringList('[gpt-4.1,claude-sonnet-4-6,gpt-oss:120b-cloud]')).toEqual([
      'gpt-4.1',
      'claude-sonnet-4-6',
      'gpt-oss:120b-cloud',
    ]);
  });

  it('returns empty for blank input', () => {
    expect(parseEnvStringList('')).toEqual([]);
    expect(parseEnvStringList(undefined)).toEqual([]);
  });
});
