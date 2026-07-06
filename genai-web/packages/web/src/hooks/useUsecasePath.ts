import { useLocation, useParams } from 'react-router';
import { pathnameToUsecase } from '@/utils/usecasePath';

export const useUsecasePath = () => {
  const { pathname } = useLocation();
  const { chatId } = useParams();
  const usecase = pathnameToUsecase(pathname);

  return { usecase, chatId, pathname };
};
