import type { FormComponent } from '../types';

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

export const formatAnswerValue = (type: string, value: unknown): string => {
  if (value == null || value === '') return '（未入力）';
  if (type === 'password') return '••••';
  if (type === 'signature_pad') return '（署名あり）';
  if (type === 'file') {
    if (typeof value === 'string' && value.trim()) return value;
    if (isRecord(value) && (value.filename || value.file_id)) {
      return String(value.filename || '（添付あり）');
    }
    return '（未入力）';
  }
  if (Array.isArray(value)) return value.length ? value.map(String).join('、') : '（未入力）';
  if (isRecord(value)) {
    if (value.start || value.end) return `${value.start || '—'} 〜 ${value.end || '—'}`;
    if (value.lat != null && value.lng != null) return `${value.lat}, ${value.lng}`;
    if (value.extracted != null || value.filename != null || value.file_id != null) {
      const name = String(value.filename || '').trim();
      const text = String(value.extracted || '').trim();
      return [name, text].filter(Boolean).join(' / ') || '（未入力）';
    }
    const parts = Object.entries(value)
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `${k}: ${v}`);
    return parts.join('、') || '（未入力）';
  }
  return String(value);
};

export const answerRows = (
  components: FormComponent[],
  answers: Record<string, unknown>,
): Array<{ id: string; label: string; value: string }> =>
  components
    .filter((c) => !['text_display', 'image_display', 'divider', 'page_break'].includes(c.type))
    .map((c) => ({
      id: c.id,
      label: c.label || c.id,
      value: formatAnswerValue(c.type, answers[c.id]),
    }));
