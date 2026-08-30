export type ChoiceOption = { value: string; label: string };

export const choiceOptions = (raw: unknown): ChoiceOption[] => {
  if (raw == null) return [];
  const items = Array.isArray(raw)
    ? raw
    : String(raw)
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
  const out: ChoiceOption[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    let value = '';
    let label = '';
    if (typeof item === 'string') {
      const text = item.trim();
      if (!text) continue;
      if (text.includes('|')) {
        const [left, ...rest] = text.split('|');
        label = left.trim();
        value = rest.join('|').trim();
      } else {
        label = value = text;
      }
    } else if (item && typeof item === 'object') {
      const rec = item as { value?: unknown; label?: unknown };
      value = String(rec.value ?? rec.label ?? '').trim();
      label = String(rec.label ?? rec.value ?? '').trim();
    }
    if (!value && label) value = label;
    if (!label && value) label = value;
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label });
  }
  return out;
};

export const parseOptionLines = (text: string): ChoiceOption[] => choiceOptions(text);

export const serializeOptions = (raw: unknown): string =>
  choiceOptions(raw)
    .map((item) => (item.label === item.value ? item.label : `${item.label}|${item.value}`))
    .join('\n');

export const optionLabel = (raw: unknown, value: unknown): string => {
  const text = value == null ? '' : String(value);
  const found = choiceOptions(raw).find((item) => item.value === text || item.label === text);
  return found?.label || text;
};
