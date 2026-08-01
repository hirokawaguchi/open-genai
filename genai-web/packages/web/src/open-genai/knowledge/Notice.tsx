import { useCallback, useState } from 'react';
import { isApiError } from '@/lib/fetcher';

export type NoticeState = { type: 'success' | 'error'; text: string } | null;

/** 操作結果の通知バナー状態を扱う小さなフック。 */
export const useNotice = () => {
  const [notice, setNotice] = useState<NoticeState>(null);
  const success = useCallback((text: string) => setNotice({ type: 'success', text }), []);
  const fail = useCallback((e: unknown, fallback: string) => {
    let text = fallback;
    if (isApiError(e)) {
      const data = e.data as { error?: string } | undefined;
      if (data?.error) text = data.error;
    } else if (e instanceof Error && e.message) {
      text = e.message;
    }
    setNotice({ type: 'error', text });
  }, []);
  const clear = useCallback(() => setNotice(null), []);
  return { notice, success, fail, clear };
};

export const Notice = ({ notice }: { notice: NoticeState }) => {
  if (!notice) return null;
  const isError = notice.type === 'error';
  return (
    <div
      role={isError ? 'alert' : 'status'}
      className={`rounded-8 border px-4 py-3 text-oln-16N-100 whitespace-pre-wrap ${
        isError
          ? 'border-error-1 bg-red-50 text-error-2'
          : 'border-green-800 bg-green-50 text-green-900'
      }`}
    >
      {notice.text}
    </div>
  );
};
