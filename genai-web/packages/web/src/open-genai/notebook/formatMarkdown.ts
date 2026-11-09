import type { NotebookCitation } from './types';

/** CommonMark は **「…」** のように約物に挟まれると強調にならない。 */
const WORD_JOINER = '\u2060';

export const formatNotebookMarkdown = (raw: string): string => {
  const md = (raw || '').replace(/\uFF0A\uFF0A/g, '**');
  return md.replace(/\*\*([^*]+)\*\*/g, `**${WORD_JOINER}$1${WORD_JOINER}**`);
};

const CITATION_MARK = /\[\s*\d+(?:\s*[,、]\s*\d+)*\s*\]/g;
const SOURCE_ONLY_LINE = /^(?:[-*+]|\d+[.)])?\s*【出典】[\s,、.。・]*$/;

/** 引用番号だけを消す。行頭の字下げは残し、出典だけの行は捨てる。 */
export const stripCitationMarks = (text: string): string => {
  const kept: string[] = [];
  for (const line of (text || '').replace(/\r\n/g, '\n').split('\n')) {
    const indent = /^[ \t]*/.exec(line)?.[0] ?? '';
    const body = line
      .slice(indent.length)
      .replace(CITATION_MARK, '')
      .replace(/ {2,}/g, ' ')
      .replace(/[ \t]+$/g, '');
    if (SOURCE_ONLY_LINE.test(body)) continue;
    kept.push(indent + body);
  }
  return kept
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\n+|\n+$/g, '');
};

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
