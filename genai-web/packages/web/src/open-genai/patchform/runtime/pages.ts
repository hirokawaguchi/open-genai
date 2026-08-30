import type { FormComponent } from '../types';

export const splitPages = (components: FormComponent[]): FormComponent[][] => {
  const pages: FormComponent[][] = [[]];
  for (const c of components) {
    if (c.type === 'page_break') {
      pages.push([]);
      continue;
    }
    pages[pages.length - 1].push(c);
  }
  return pages.filter((page) => page.length > 0);
};

export const nextFilledPage = (
  pages: FormComponent[][],
  from: number,
  direction: 1 | -1,
  hasContent: (page: FormComponent[]) => boolean,
): number => {
  let i = from + direction;
  while (i >= 0 && i < pages.length) {
    if (hasContent(pages[i])) return i;
    i += direction;
  }
  return Math.max(0, Math.min(pages.length - 1, from));
};
