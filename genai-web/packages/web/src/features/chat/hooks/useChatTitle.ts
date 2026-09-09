import { useParams } from 'react-router';
import { useFetchExApp } from '@/features/exapp/hooks/useFetchExApp';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useChatList } from '@/hooks/useChatList';

const FALLBACK_APP_NAME = 'チャット';

export const useChatTitle = (chatTitleFromStore?: string) => {
  const { chatId } = useParams();
  const { getChatTitle } = useChatList();
  const { data: chatApp } = useFetchExApp(COMMON_EXAPPS_TEAM_ID, 'chat');
  const appName = (chatApp?.exAppName || '').trim() || FALLBACK_APP_NAME;
  const description = (chatApp?.description || '').trim();

  const pageTitle = chatId ? getChatTitle(chatId) || appName : appName;
  const title = chatId ? pageTitle : chatTitleFromStore || appName;

  return {
    title,
    pageTitle,
    appName,
    description,
  };
};
