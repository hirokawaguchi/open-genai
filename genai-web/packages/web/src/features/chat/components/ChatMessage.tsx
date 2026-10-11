import type { ShownMessage } from 'genai-web';
import { AssistantMessage } from '@/features/chat/components/AssistantMessage';
import { UserMessage } from '@/features/chat/components/UserMessage';

type Props = {
  idx?: number;
  chatContent: ShownMessage;
  chatId?: string;
  loading?: boolean;
  allowRetry?: boolean;
  retryGeneration?: () => void;
};

export const ChatMessage = ({ chatContent, ...rest }: Props) => {
  if (chatContent.role === 'user') {
    return <UserMessage chatContent={chatContent} />;
  }

  if (chatContent.role === 'assistant') {
    return <AssistantMessage chatContent={chatContent} {...rest} />;
  }

  return null;
};
