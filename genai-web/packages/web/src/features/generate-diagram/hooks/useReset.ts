import { useEffect } from 'react';
import { useShouldResetOnNavigate } from '@/hooks/useShouldResetOnNavigate';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useDiagramStore } from '../stores/useDiagramStore';
import { useDiagram } from './useDiagram';

export const useReset = () => {
  const { shouldReset } = useShouldResetOnNavigate();
  const { clear } = useDiagramStore();
  const { usecase, chatId } = useUsecasePath();
  const { clear: clearChat } = useDiagram(usecase, chatId);

  useEffect(() => {
    if (!shouldReset) {
      return;
    }

    clear();
    clearChat();
  }, [shouldReset]);
};
