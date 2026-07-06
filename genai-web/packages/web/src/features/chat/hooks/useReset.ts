import { useEffect } from 'react';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useFiles } from '@/hooks/useFiles';
import { useShouldResetOnNavigate } from '@/hooks/useShouldResetOnNavigate';
import { useChatStore } from '../stores/useChatStore';

export const useReset = () => {
  const { shouldReset } = useShouldResetOnNavigate();
  const { usecase, chatId } = useUsecasePath();
  const { clear } = useChat(usecase, chatId);
  const { clear: clearFiles } = useFiles(usecase);
  const { setContent, setSystemContextTitle, setHasSent } = useChatStore();

  // eslint-disable-next-line react-hooks/exhaustive-deps -- 関数は毎回新しい参照になるため依存配列から除外
  useEffect(() => {
    if (!shouldReset) {
      return;
    }

    clear();
    clearFiles();
    setContent('');
    setSystemContextTitle('');
    setHasSent(false);
  }, [shouldReset]);
};
