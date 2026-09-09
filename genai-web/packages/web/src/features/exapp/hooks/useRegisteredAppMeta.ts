import { APP_TITLE } from '@/constants';
import { useFetchExApp } from '@/features/exapp/hooks/useFetchExApp';

/** 「AIアプリの編集」に登録した名前・紹介を、専用ページの見出し／タブに使う。 */
export const useRegisteredAppMeta = (
  teamId: string,
  exAppId: string,
  fallbackTitle: string,
  fallbackDescription = '',
  enabled = true,
) => {
  const { data: exApp, isLoading } = useFetchExApp(enabled ? teamId : '', enabled ? exAppId : '');
  const title = (exApp?.exAppName || '').trim() || fallbackTitle;
  const description = (exApp?.description || '').trim() || fallbackDescription;
  const howToUse = (exApp?.howToUse || '').trim();
  const documentTitle = `${title}${APP_TITLE ? ` | ${APP_TITLE}` : ''}`;
  return { title, description, howToUse, documentTitle, exApp, isLoading };
};
