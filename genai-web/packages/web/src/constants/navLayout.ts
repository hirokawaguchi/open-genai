export type NavLayout = 'header' | 'sidebar';

/**
 * ナビ配置。VITE_APP_NAV_LAYOUT=header|sidebar（未設定は sidebar。header 以外の不正値も sidebar）。
 * 静的ビルド時はビルド引数 / .env に埋め込む。
 */
export const getNavLayout = (): NavLayout => {
  const value = (import.meta.env.VITE_APP_NAV_LAYOUT ?? 'sidebar').trim().toLowerCase();
  return value === 'header' ? 'header' : 'sidebar';
};

export const isSidebarNavLayout = (): boolean => getNavLayout() === 'sidebar';
