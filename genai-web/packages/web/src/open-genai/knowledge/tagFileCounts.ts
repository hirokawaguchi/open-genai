import type { KnowledgeDoc } from './types';

export type TagFileCount = {
  tag: string;
  /** 失敗していない文書の数。処理中も含む。 */
  files: number;
  pending: number;
};

/** タグごとの文書数。取り込みに失敗した文書は数えない。 */
export const tagFileChoices = (docs: KnowledgeDoc[]): TagFileCount[] => {
  const files = new Map<string, number>();
  const pending = new Map<string, number>();
  for (const doc of docs) {
    if (doc.ingest_status === 'failed') continue;
    const waiting = doc.ingest_status === 'queued' || doc.ingest_status === 'processing';
    for (const raw of doc.tags ?? []) {
      const name = raw.trim();
      if (!name) continue;
      files.set(name, (files.get(name) ?? 0) + 1);
      if (waiting) pending.set(name, (pending.get(name) ?? 0) + 1);
    }
  }
  return [...files.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], 'ja'))
    .map(([tag, count]) => ({
      tag,
      files: count,
      pending: pending.get(tag) ?? 0,
    }));
};
