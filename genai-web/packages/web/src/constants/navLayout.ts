export type NavLayout = 'header' | 'sidebar';

/**
 * ナビ配置。VITE_APP_NAV_LAYOUT=header|sidebar（未設定・不正値は header）。
 * 静的ビルド時はビルド引数 / .env に埋め込む。
 */
export const getNavLayout = (): NavLayout => {
  const value = (import.meta.env.VITE_APP_NAV_LAYOUT ?? 'header').trim().toLowerCase();
  return value === 'sidebar' ? 'sidebar' : 'header';
};

export const isSidebarNavLayout = (): boolean => getNavLayout() === 'sidebar';
