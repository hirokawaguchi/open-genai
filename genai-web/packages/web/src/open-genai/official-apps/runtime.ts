export const ALWAYS_ON_OFFICIAL_APP_IDS = new Set([
  'chat',
  'generate',
  'translate',
  'diagram',
  'knowledge',
  'rag',
]);

export type OfficialAppsRuntime = {
  catalog?: string[];
  running: string[];
};

export type OfficialAppRuntimeKind = 'running' | 'stopped' | 'unknown';

export const OFFICIAL_APP_RUNTIME_LABEL: Record<OfficialAppRuntimeKind, string> = {
  running: '起動中',
  stopped: '未起動',
  unknown: '',
};

/** 起動中の公式アプリだけ残す。利用者向け一覧用。未取得時は本体同梱の常時アプリのみ。 */
export const filterRunningOfficialOptions = <T extends { id: string }>(
  options: readonly T[],
  running: readonly string[] | undefined,
): T[] => {
  const allow = running ? new Set(running) : ALWAYS_ON_OFFICIAL_APP_IDS;
  return options.filter((opt) => allow.has(opt.id));
};

export const officialAppRuntimeKind = (
  id: string,
  running: readonly string[] | undefined,
): OfficialAppRuntimeKind => {
  if (ALWAYS_ON_OFFICIAL_APP_IDS.has(id)) {
    return 'running';
  }
  if (!running) {
    return 'unknown';
  }
  return running.includes(id) ? 'running' : 'stopped';
};
