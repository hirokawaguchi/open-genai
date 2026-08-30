import type { FormComponent } from '../types';
import { choiceOptions } from './choiceOptions';

const norm = (value: string) => value.replace(/\s+/g, '').toLowerCase();

const matchesPrepare = (option: { value: string; label: string }, prepare: string[]) => {
  const tokens = [norm(option.value), norm(option.label)].filter(Boolean);
  return prepare.some((item) => {
    const needle = norm(item);
    if (!needle) return false;
    return tokens.some((token) => token === needle || token.includes(needle) || needle.includes(token));
  });
};

/** 持ち物の文言に当たるチェックボックスを、空のときだけ入れる。 */
export const seedPrepare = (
  components: FormComponent[],
  values: Record<string, unknown>,
  prepare: string[],
): Record<string, unknown> => {
  const items = (prepare || []).map((s) => s.trim()).filter(Boolean);
  if (items.length === 0) return {};
  const out: Record<string, unknown> = {};
  for (const c of components) {
    if (c.type !== 'checkbox') continue;
    const current = values[c.id];
    if (Array.isArray(current) && current.length > 0) continue;
    if (typeof current === 'string' && current.trim()) continue;
    const picked = choiceOptions(c.properties?.options)
      .filter((opt) => matchesPrepare(opt, items))
      .map((opt) => opt.value);
    if (picked.length) out[c.id] = picked;
  }
  return out;
};
