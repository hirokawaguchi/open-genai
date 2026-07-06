import { useEffect } from 'react';
import { useChat } from '@/hooks/useChat';
import { useShouldResetOnNavigate } from '@/hooks/useShouldResetOnNavigate';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useGenerateImageStore } from '../stores/useGenerateImageStore';

export const useReset = () => {
  const { shouldReset } = useShouldResetOnNavigate();
  const { usecase, chatId } = useUsecasePath();
  const { clear: clearChat } = useChat(usecase, chatId);
  const { clearImage, clear } = useGenerateImageStore();

  useEffect(() => {
    if (!shouldReset) {
      return;
    }

    clear();
    clearChat();
    clearImage();
  }, [shouldReset]);
};
