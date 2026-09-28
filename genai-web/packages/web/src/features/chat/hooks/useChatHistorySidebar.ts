import { useChatApi } from '@/hooks/useChatApi';
import { resolveChatUsecase } from '@/utils/usecasePath';

const DISPLAY_COUNT = 5;

export type ChatHistoryScope = 'image' | 'chat';

export const useChatHistorySidebar = (scope?: ChatHistoryScope) => {
  const { listChats } = useChatApi();
  const { data, isLoading } = listChats();

  const allChats = (data?.flatMap((page) => page.data) ?? []).filter((chat) => {
    const usecase = resolveChatUsecase(chat);
    if (scope === 'image') {
      return usecase === '/image';
    }
    if (scope === 'chat') {
      return usecase !== '/image';
    }
    return true;
  });
  const displayedChats = allChats.slice(0, DISPLAY_COUNT);

  return { displayedChats, isLoading };
};
