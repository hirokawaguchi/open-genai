const ANSWER_REF = /\[\[回答\s*(\d+)\]\]/g;

export const MAX_ANSWER_REFS = 5;

export const answerRefToken = (n: number): string => `[[回答 ${n}]]`;

export const answerRefNumbers = (text: string): number[] => {
  const seen: number[] = [];
  for (const match of (text || '').matchAll(ANSWER_REF)) {
    const n = Number(match[1]);
    if (!seen.includes(n)) seen.push(n);
  }
  return seen;
};

export const numberedAssistantMessages = <T extends { role: string; content: string }>(
  messages: T[],
): { n: number; message: T }[] => {
  const out: { n: number; message: T }[] = [];
  let n = 0;
  for (const message of messages) {
    if (message.role === 'assistant' && message.content.trim()) {
      n += 1;
      out.push({ n, message });
    }
  }
  return out;
};

export const answerPreviewLine = (content: string, limit = 40): string => {
  const line = (content || '')
    .trim()
    .split(/\r?\n/, 1)[0]
    ?.replace(/\s+/g, ' ')
    .trim();
  if (!line) return '';
  if (line.length <= limit) return line;
  return `${line.slice(0, limit)}…`;
};

export const insertAnswerRef = (
  value: string,
  n: number,
  start: number,
  end: number,
): { value: string; caret: number } => {
  const token = answerRefToken(n);
  const before = value.slice(0, start);
  const after = value.slice(end);
  const padBefore = before && !/\s$/.test(before) ? ' ' : '';
  const padAfter = after && !/^\s/.test(after) ? ' ' : '';
  const next = `${before}${padBefore}${token}${padAfter}${after}`;
  return { value: next, caret: (before + padBefore + token).length };
};
