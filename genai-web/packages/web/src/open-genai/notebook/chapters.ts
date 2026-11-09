import { stripCitationMarks } from './formatMarkdown';

export type NotebookChapter = {
  label: string;
  value: string;
};

/** 回答中の Markdown 見出しを、項目の見出しと本文に分ける。見出しが無ければ空。 */
export const chaptersFromAnswer = (text: string): NotebookChapter[] => {
  const clean = stripCitationMarks(text).replace(/\r\n/g, '\n').trim();
  if (!clean) return [];
  const marks: { index: number; end: number; label: string }[] = [];
  const re = /^#{1,3}[ \t]+(.+)$/gm;
  for (const match of clean.matchAll(re)) {
    const label = match[1].replace(/\s+#+\s*$/, '').trim();
    if (!label) continue;
    marks.push({ index: match.index, end: match.index + match[0].length, label });
  }
  if (marks.length === 0) return [];
  const preface = clean.slice(0, marks[0].index).trim();
  return marks.map((mark, index) => {
    const stop = index + 1 < marks.length ? marks[index + 1].index : clean.length;
    let value = clean.slice(mark.end, stop).trim();
    if (index === 0 && preface) {
      value = value ? `${preface}\n\n${value}` : preface;
    }
    return { label: mark.label.slice(0, 200), value };
  });
};
