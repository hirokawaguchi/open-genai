import { describe, expect, it } from 'vitest';
import { tagFileChoices } from '../../../src/open-genai/knowledge/tagFileCounts';
import type { KnowledgeDoc } from '../../../src/open-genai/knowledge/types';

const doc = (source: string, tags: string[], ingest_status?: KnowledgeDoc['ingest_status']): KnowledgeDoc => ({
  doc_id: source,
  scope: 'team',
  source,
  tags,
  page_count: 1,
  char_count: 1,
  index_kind: 'tree',
  ingest_status,
});

describe('tagFileChoices', () => {
  it('タグごとの文書数を数える', () => {
    const choices = tagFileChoices([
      doc('a.pdf', ['規程', '議事録']),
      doc('b.pdf', ['規程']),
      doc('c.pdf', [' 議事録 ']),
    ]);
    expect(choices).toEqual([
      { tag: '規程', files: 2, pending: 0 },
      { tag: '議事録', files: 2, pending: 0 },
    ]);
  });

  it('失敗した文書は数えない', () => {
    const choices = tagFileChoices([
      doc('ok.pdf', ['規程'], 'ready'),
      doc('bad.pdf', ['規程'], 'failed'),
      doc('wait.pdf', ['規程'], 'processing'),
    ]);
    expect(choices).toEqual([{ tag: '規程', files: 2, pending: 1 }]);
  });
});
