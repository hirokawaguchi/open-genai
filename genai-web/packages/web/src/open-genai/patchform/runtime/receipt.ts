import type { Application, FormComponent } from '../types';
import { answerRows } from './formatAnswer';

// 控え（テキスト）に含めない／伏せる機微な部品タイプ。
const SENSITIVE_TYPES = new Set(['mynumber']);

const maskedRows = (
  components: FormComponent[],
  answers: Record<string, unknown>,
): Array<{ label: string; value: string }> =>
  answerRows(components, answers).map((row) => {
    const comp = components.find((c) => c.id === row.id);
    if (comp && SENSITIVE_TYPES.has(comp.type)) {
      const filled = row.value && row.value !== '（未入力）';
      return { label: row.label, value: filled ? '********（マイナンバー・非表示）' : row.value };
    }
    return { label: row.label, value: row.value };
  });

const fmtDate = (d?: Date | string | null): string => {
  if (!d) return new Date().toLocaleString('ja-JP');
  const dd = typeof d === 'string' ? new Date(d) : d;
  return Number.isNaN(dd.getTime()) ? String(d) : dd.toLocaleString('ja-JP');
};

const safeName = (s: string): string =>
  (s || '控え').replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 40);

/** テキストを .txt としてその場でダウンロードさせる。 */
export const downloadTextFile = (filename: string, text: string): void => {
  // BOM を付け、Windows のメモ帳等でも文字化けしないようにする。
  const blob = new Blob(['\uFEFF', text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

export type SingleFormReceiptInput = {
  title: string;
  receiptCode: string;
  components: FormComponent[];
  answers: Record<string, unknown>;
  submitterName?: string | null;
  submittedAt?: Date | string | null;
  note?: string;
};

/** 単一フォーム提出の控え（受付番号＋回答内容）テキストを組み立てる。 */
export const buildSingleFormReceipt = (input: SingleFormReceiptInput): string => {
  const lines: string[] = [];
  lines.push('【申請の控え】');
  lines.push('');
  lines.push(`フォーム: ${input.title}`);
  lines.push(`受付番号（控え番号）: ${input.receiptCode || '—'}`);
  if (input.submitterName) lines.push(`お名前: ${input.submitterName}`);
  lines.push(`提出日時: ${fmtDate(input.submittedAt)}`);
  lines.push('');
  lines.push('― 回答内容 ―');
  const rows = maskedRows(input.components, input.answers);
  if (!rows.length) lines.push('（回答なし）');
  for (const row of rows) lines.push(`${row.label}: ${row.value}`);
  if (input.note) {
    lines.push('');
    lines.push(input.note);
  }
  lines.push('');
  lines.push('※この控えはお使いの端末で生成したものです。大切に保管してください。');
  return lines.join('\n');
};

export const downloadSingleFormReceipt = (input: SingleFormReceiptInput): void => {
  downloadTextFile(
    `控え_${safeName(input.title)}_${input.receiptCode || ''}.txt`,
    buildSingleFormReceipt(input),
  );
};

const itemStatusLabel = (status: string, fileAttached?: boolean): string => {
  if (status === 'submitted') return '提出済';
  if (status === 'draft') return '下書き';
  if (status === 'withdrawn') return '取下げ';
  if (fileAttached) return '添付あり';
  return '未';
};

export type ApplicationReceiptInput = {
  application: Application;
  note?: string;
};

/** 申請束（マイ手続き）の控えテキストを組み立てる。 */
export const buildApplicationReceipt = ({
  application,
  note,
}: ApplicationReceiptInput): string => {
  const lines: string[] = [];
  lines.push('【申請の控え】');
  lines.push('');
  lines.push(`手続き: ${application.procedure_name || application.title || '—'}`);
  if (application.title && application.title !== application.procedure_name) {
    lines.push(`件名: ${application.title}`);
  }
  lines.push(`受付番号（申請ID）: ${application.id}`);
  lines.push(`状態: ${application.status?.effective || '—'}`);
  lines.push(`作成日時: ${fmtDate(application.created_at)}`);
  lines.push('');
  lines.push('― 提出書類 ―');
  const items = application.items || [];
  if (!items.length) lines.push('（書類なし）');
  for (const item of items) {
    lines.push(`● ${item.title}  [${itemStatusLabel(item.status, item.file_attached)}]`);
    if (item.file_name) lines.push(`  添付ファイル: ${item.file_name}`);
    if (item.answers && item.definition) {
      for (const row of maskedRows(item.definition.components, item.answers)) {
        if (row.value && row.value !== '（未入力）') {
          lines.push(`  ${row.label}: ${row.value}`);
        }
      }
    }
  }
  if (note) {
    lines.push('');
    lines.push(note);
  }
  lines.push('');
  lines.push('※この控えはお使いの端末で生成したものです。大切に保管してください。');
  return lines.join('\n');
};

export const downloadApplicationReceipt = ({
  application,
  note,
}: ApplicationReceiptInput): void => {
  downloadTextFile(
    `控え_${safeName(application.procedure_name || application.title || 'application')}_${application.id.slice(0, 8)}.txt`,
    buildApplicationReceipt({ application, note }),
  );
};
