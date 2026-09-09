import { useExAppCatalog } from '@/features/exapps/hooks/useExAppCatalog';
import { getUsecaseLabel } from '@/utils/usecasePath';

const USECASE_EXAPP_IDS: Record<string, string> = {
  '/chat': 'chat',
  '/image': 'image',
  '/diagram': 'diagram',
  '/generate': 'generate',
  '/translate': 'translate',
};

/** 利用履歴などに出すユースケース名。登録済みなら「AIアプリの編集」の名前を使う。 */
export const useUsecaseLabelFn = () => {
  const { apps, loaded } = useExAppCatalog();
  const names = new Map(
    apps.map((a) => [a.exAppId, (a.exAppName || '').trim()] as const),
  );
  return (usecase: string) => {
    if (loaded) {
      const id = USECASE_EXAPP_IDS[usecase];
      const name = id ? names.get(id) : '';
      if (name) {
        return name;
      }
    }
    return getUsecaseLabel(usecase);
  };
};
