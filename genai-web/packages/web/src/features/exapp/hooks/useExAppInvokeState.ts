import type { InvokeExAppRequest } from 'genai-web';
import { isApiError } from '@/lib/fetcher';
import { useExAppInvokeStore } from '../stores/useExAppInvokeStore';
import { useInvokeExApp } from './useInvokeExApp';

export const useExAppInvokeState = () => {
  const { invokeExApp } = useInvokeExApp();
  const store = useExAppInvokeStore();

  const invokeRequest = async (req: InvokeExAppRequest) => {
    try {
      const res = await invokeExApp(req);
      store.setExAppResponse(res);
    } catch (error: unknown) {
      store.setExAppResponse(null);
      if (isApiError(error)) {
        const data = error.data as { error?: string };
        throw new Error(
          data?.error ||
            '処理中にエラーが発生しました。時間をおいて再度お試しください。解消しない場合は管理者にお問い合わせください。',
        );
      } else if (error instanceof Error) {
        throw new Error(error.message);
      }
    }
  };

  return {
    ...store,
    invokeRequest,
  };
};
