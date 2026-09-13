import type { NotebookCitation } from './types';

/** CommonMark は **「…」** のように約物に挟まれると強調にならない。 */
const WORD_JOINER = '\u2060';

export const formatNotebookMarkdown = (raw: string): string => {
  const md = (raw || '').replace(/\uFF0A\uFF0A/g, '**');
  return md.replace(/\*\*([^*]+)\*\*/g, `**${WORD_JOINER}$1${WORD_JOINER}**`);
};

export const stripCitationMarks = (text: string): string =>
  (text || '')
    .replace(/\[\s*\d+(?:\s*[,、]\s*\d+)*\s*\]/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/ {2,}/g, ' ')
    .trim();

export const citationNumber = (c: NotebookCitation): number => {
  if (typeof c.n === 'number' && c.n > 0) return c.n;
  const m = /^\[(\d+)\]/.exec(c.display_name || '');
  return m ? Number(m[1]) : 0;
};

export const usedCitations = (text: string, cites: NotebookCitation[]): NotebookCitation[] => {
  const used = new Set(
    [...(text || '').matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])),
  );
  return cites.filter((c) => used.has(citationNumber(c)));
};

export const sourceLabel = (c: NotebookCitation): string =>
  (c.display_name || '').replace(/^\[\d+\]\s*/, '');

export const linkifyCitationMarks = (md: string, idPrefix: string): string =>
  (md || '').replace(/\[(\d+)\]/g, (_all, n: string) => `[[${n}]](#${idPrefix}-${n})`);
