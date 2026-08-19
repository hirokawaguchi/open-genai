const SAFE = /^[0-9+\-*/().\s]+$/;
const FIELD_REF = /\{\{([a-zA-Z0-9_]+)\}\}/g;

const asNumberText = (value: unknown): string => {
  if (value == null || value === '') return '';
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  const n = Number(String(value).replace(/,/g, ''));
  return Number.isFinite(n) ? String(n) : '';
};

export const evaluateFormula = (
  formula: string,
  values: Record<string, unknown>,
): number | null => {
  const expr = (formula || '').replace(FIELD_REF, (_m, id: string) => asNumberText(values[id]));
  if (!expr.trim() || !SAFE.test(expr)) return null;
  try {
    const result = Function(`"use strict"; return (${expr})`)();
    return typeof result === 'number' && Number.isFinite(result) ? result : null;
  } catch {
    return null;
  }
};

export const formatCalculated = (value: unknown): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
};
