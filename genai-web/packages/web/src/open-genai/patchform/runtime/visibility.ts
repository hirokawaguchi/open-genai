import type { FormComponent } from '../types';

export const DISPLAY_TYPES = new Set(['text_display', 'image_display', 'divider', 'page_break']);

const asStrings = (value: unknown): string[] => {
  if (value == null || value === '') return [''];
  if (Array.isArray(value)) return value.map((v) => String(v));
  return [String(value)];
};

const ruleMatches = (value: unknown, rule: { eq?: string; in?: string[] }): boolean => {
  const got = asStrings(value);
  if (rule.eq !== undefined) return got.includes(String(rule.eq));
  if (rule.in) return rule.in.some((item) => got.includes(String(item)));
  return true;
};

export const isVisible = (c: FormComponent, values: Record<string, unknown>): boolean => {
  const cond = c.visibleWhen;
  if (!cond) return true;
  const rules = Array.isArray(cond) ? cond : [cond];
  return rules.every((rule) => ruleMatches(values[rule.field], rule));
};

export const isAnswerEmpty = (type: string, value: unknown): boolean => {
  if (value == null || value === '') return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') {
    const rec = value as Record<string, unknown>;
    if ('file_id' in rec || 'filename' in rec) {
      return !String(rec.file_id || '').trim() && !String(rec.filename || '').trim();
    }
    return !Object.values(rec).some((v) => v != null && v !== '' && v !== false);
  }
  return false;
};

export const missingRequired = (
  components: FormComponent[],
  values: Record<string, unknown>,
): FormComponent | undefined =>
  components.find(
    (c) =>
      !!c.required &&
      !DISPLAY_TYPES.has(c.type) &&
      c.type !== 'calculated' &&
      isVisible(c, values) &&
      isAnswerEmpty(c.type, values[c.id]),
  );
