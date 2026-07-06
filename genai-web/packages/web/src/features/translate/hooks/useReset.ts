import { useEffect } from 'react';
import { useChat } from '@/hooks/useChat';
import { useShouldResetOnNavigate } from '@/hooks/useShouldResetOnNavigate';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useTranslateStore } from '../stores/useTranslateStore';

export const useReset = () => {
  const { shouldReset } = useShouldResetOnNavigate();
  const { clear } = useTranslateStore();
  const { usecase, chatId } = useUsecasePath();
  const { clear: clearChat } = useChat(usecase, chatId);

  useEffect(() => {
    if (!shouldReset) {
      return;
    }

    clear();
    clearChat();
  }, [shouldReset]);
};
