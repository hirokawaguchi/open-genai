import type { FieldValues } from 'react-hook-form';
import type {
  GovAIFormCondition,
  GovAIFormUIItem,
  GovAIFormUIJson,
  GovAIFormVisibleWhen,
  GovAIListItem,
} from '../types';

/** OpenGENAI exApp Form Spec v1 の予約キー（フォームには描画しない）。 */
export const isReservedFormKey = (key: string): boolean => key.startsWith('$');

const toConditions = (v: GovAIFormVisibleWhen): GovAIFormCondition[] =>
  Array.isArray(v) ? v : [v];

/**
 * visibleWhen を現在のフォーム値で評価する。未指定なら常に true（従来動作）。
 * 配列指定時は全条件を満たす場合のみ true（AND）。
 */
export const isFieldVisible = (uiConfig: GovAIFormUIItem, values: FieldValues): boolean => {
  const visibleWhen = (uiConfig as { visibleWhen?: GovAIFormVisibleWhen }).visibleWhen;
  if (!visibleWhen) {
    return true;
  }
  return toConditions(visibleWhen).every((cond) => {
    const current = values?.[cond.field];
    return cond.in.includes(current == null ? '' : String(current));
  });
};

const VAR_RE = /\{\{\s*([^}]+?)\s*\}\}/g;

/**
 * template 中の {{キー}} をフォーム値で置換する。未指定キーはそのまま残す。
 * prompt-app 側 catalog.substitute と同等の挙動。
 */
export const substituteTemplate = (template: string, values: FieldValues): string => {
  return (template || '').replace(VAR_RE, (match, rawKey: string) => {
    const key = rawKey.trim();
    const value = values?.[key];
    if (value === undefined || value === null || value === '') {
      return match;
    }
    return String(value);
  });
};

/**
 * OpenGENAI Form Spec v1: 現在の選択内容に確認が必要なら、その確認メッセージを返す。
 * 表示中(visibleWhen 通過)の select/radio について、選択値の item.confirm を探す。
 * 不可逆操作（削除など）で実行前に確認ダイアログを出すために使う。
 */
export const getConfirmMessage = (
  uiJson: GovAIFormUIJson,
  values: FieldValues,
): string | null => {
  for (const key of Object.keys(uiJson)) {
    if (isReservedFormKey(key)) {
      continue;
    }
    const uiConfig = uiJson[key];
    if (!isFieldVisible(uiConfig, values)) {
      continue;
    }
    const items = (uiConfig as { items?: GovAIListItem[] }).items;
    if (!items) {
      continue;
    }
    const current = values?.[key];
    const cur = current == null ? '' : String(current);
    const hit = items.find((i) => i.value === cur && i.confirm);
    if (hit?.confirm) {
      return hit.confirm;
    }
  }
  return null;
};

/** template 中で未入力の {{キー}} 一覧（重複なし）。 */
export const missingTemplateVars = (template: string, values: FieldValues): string[] => {
  const missing: string[] = [];
  for (const match of (template || '').matchAll(new RegExp(VAR_RE))) {
    const key = match[1].trim();
    const value = values?.[key];
    if ((value === undefined || value === null || value === '') && !missing.includes(key)) {
      missing.push(key);
    }
  }
  return missing;
};
