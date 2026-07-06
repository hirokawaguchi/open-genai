import type { Chat } from 'genai-web';
import { decomposeId } from '@/utils/decomposeId';

export const USECASE_LABELS: Record<string, string> = {
  '/chat': 'チャット',
  '/image': '画像生成',
  '/diagram': 'ダイアグラム',
  '/generate': '文章生成',
  '/translate': '翻訳',
};

/** `/image/uuid` → `/image` のようにユースケースパスへ正規化する */
export const pathnameToUsecase = (pathname: string): string => {
  const match = pathname.match(/^\/([^/]+)/);
  return match ? `/${match[1]}` : '/chat';
};

/** チャットレコードから表示・リンク用の usecase を解決する */
export const resolveChatUsecase = (chat: Chat): string => {
  const raw = chat.usecase?.trim() ?? '';
  if (raw.startsWith('/')) {
    if (raw !== '/chat' && raw !== '') {
      return raw;
    }
  } else if (raw !== '' && raw !== 'chat') {
    return raw.startsWith('/') ? raw : `/${raw}`;
  }
  return '/chat';
};

export const getUsecaseLabel = (usecase: string): string => {
  return USECASE_LABELS[usecase] ?? USECASE_LABELS['/chat'];
};

export const getChatHistoryLink = (chat: Chat): string => {
  const chatId = decomposeId(chat.chatId);
  if (!chatId) {
    return '/chat';
  }
  const usecase = resolveChatUsecase(chat);
  return `${usecase}/${chatId}`;
};
