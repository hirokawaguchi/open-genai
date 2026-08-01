// 本文中の {{キー}} を抽出・置換するクライアント側ユーティリティ。
// prompt-app 側 catalog.substitute / template_variables と同等の挙動。

const VAR_RE = /\{\{\s*([^}]+?)\s*\}\}/g;

/** 本文に含まれる {{キー}} の一覧（重複なし・出現順）。 */
export const extractVariables = (body: string): string[] => {
  const seen: string[] = [];
  for (const match of (body || '').matchAll(new RegExp(VAR_RE))) {
    const key = match[1].trim();
    if (!seen.includes(key)) {
      seen.push(key);
    }
  }
  return seen;
};

/** 本文中の {{キー}} を値で置換する。未入力のキーはそのまま残す。 */
export const substitute = (body: string, values: Record<string, string>): string => {
  return (body || '').replace(VAR_RE, (match, rawKey: string) => {
    const key = rawKey.trim();
    const value = values?.[key];
    if (value === undefined || value === null || value === '') {
      return match;
    }
    return value;
  });
};

/** 未入力の {{キー}} 一覧（重複なし）。 */
export const missingVariables = (body: string, values: Record<string, string>): string[] => {
  const missing: string[] = [];
  for (const match of (body || '').matchAll(new RegExp(VAR_RE))) {
    const key = match[1].trim();
    const value = values?.[key];
    if ((value === undefined || value === null || value === '') && !missing.includes(key)) {
      missing.push(key);
    }
  }
  return missing;
};
