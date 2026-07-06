import { createChat, createMessages } from '@/lib/chatApi';
import { decomposeId } from '@/utils/decomposeId';

export const buildDirectImageAssistantContent = (
  prompt: string,
  negativePrompt: string,
): string =>
  JSON.stringify({
    prompt,
    negativePrompt,
    comment: '',
    recommendedStylePreset: [],
  });

/** 画像結果を extraData に保存する assistant メッセージ ID を返す（無ければ作成） */
export async function ensureImagePersistTarget(params: {
  usecase: string;
  chatId: string | undefined;
  sessionChatId: string | undefined;
  lastAssistantMessageId: string | undefined;
  prompt: string;
  negativePrompt: string;
}): Promise<{ chatId: string; messageId: string } | null> {
  const resolvedChatId = params.chatId ?? params.sessionChatId;

  if (params.lastAssistantMessageId && resolvedChatId) {
    return { chatId: resolvedChatId, messageId: params.lastAssistantMessageId };
  }

  let chatIdForApi = resolvedChatId;
  if (!chatIdForApi) {
    const { chat } = await createChat({ usecase: params.usecase });
    chatIdForApi = decomposeId(chat.chatId) ?? chat.chatId.replace(/^chat#/, '');
  }

  const messageId = crypto.randomUUID();
  const { messages } = await createMessages(chatIdForApi, {
    messages: [
      {
        messageId,
        role: 'assistant',
        content: buildDirectImageAssistantContent(params.prompt, params.negativePrompt),
        usecase: params.usecase,
      },
    ],
  });

  const recorded = messages.find((m) => m.messageId === messageId) ?? messages.at(-1);
  if (!recorded?.messageId) {
    return null;
  }
  return { chatId: chatIdForApi, messageId: recorded.messageId };
}
