import type { ExApp, ExAppStatus } from 'genai-web';

/** 源内の汎用／専用ページを、共通アプリ編集のカタログとして扱う ID */
export const BUILTIN_EXAPP_IDS = new Set([
  'chat',
  'generate',
  'translate',
  'image',
  'diagram',
  'knowledge',
]);

type CatalogApp = Pick<ExApp, 'exAppId'> & {
  config?: string;
  status?: ExAppStatus;
};

export const isBuiltinConfig = (config?: string): boolean => {
  try {
    return (JSON.parse(config || '{}') as { builtin?: boolean }).builtin === true;
  } catch {
    return false;
  }
};

export const isBuiltinExApp = (app: { config?: string; exAppId?: string }): boolean => {
  if (isBuiltinConfig(app.config)) {
    return true;
  }
  return Boolean(app.exAppId && BUILTIN_EXAPP_IDS.has(app.exAppId));
};

export const builtinRouteOf = (config?: string): string | null => {
  try {
    const cfg = JSON.parse(config || '{}') as { builtin?: boolean; route?: string };
    if (cfg.builtin && typeof cfg.route === 'string' && cfg.route.startsWith('/')) {
      return cfg.route;
    }
  } catch {
    // ignore
  }
  return null;
};

/** カタログ取得後、公開中ならメニューに出す。未取得時は従来どおり出す。 */
export const isCatalogListed = (
  id: string,
  apps: CatalogApp[],
  loaded: boolean,
): boolean => {
  if (!loaded) {
    return true;
  }
  const app = apps.find((a) => a.exAppId === id);
  if (app) {
    return app.status !== 'draft';
  }
  // 未シードの組み込みはフォールバック表示。実 exApp が一覧に無い＝非公開または停止
  return BUILTIN_EXAPP_IDS.has(id);
};
