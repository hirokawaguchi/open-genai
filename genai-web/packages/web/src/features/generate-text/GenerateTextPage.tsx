import { PageTitle } from '@/components/PageTitle';
import { Divider } from '@/components/ui/dads/Divider';
import { APP_TITLE } from '@/constants';
import { GenerateTextForm } from '@/features/generate-text/components/GenerateTextForm';
import { GenerateTextHeader } from '@/features/generate-text/components/GenerateTextHeader';
import { GenerateTextResult } from '@/features/generate-text/components/GenerateTextResult';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useFollow } from '@/hooks/useFollow';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { usePrompter } from '@/hooks/usePrompter';
import { useTyping } from '@/hooks/useTyping';
import { LayoutBody } from '@/layout/LayoutBody';
import { useReset } from './hooks/useReset';
import { useSetDefaultValues } from './hooks/useSetDefaultValues';

export const GenerateTextPage = () => {
  const { usecase, chatId } = useUsecasePath();
  const { loading, messages, postChat } = useChat(usecase, chatId);

  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const text = lastMessage?.role === 'assistant' ? lastMessage.content.trim() : '';

  const { typingTextOutput } = useTyping(loading, text);
  const { scrollableContainer, setFollowing } = useFollow();

  const { prompter } = usePrompter();

  useReset();

  useSetDefaultValues();

  const getGeneratedText = (information: string, context: string) => {
    postChat(
      prompter.generateTextPrompt({
        information,
        context,
      }),
      { ignoreHistory: true },
    );
  };

  const { liveStatusMessage } = useLiveStatusMessage({
    active: lastMessage?.role === 'assistant',
    loading: loading,
    messages: {
      loading: 'AIが回答を生成しています...',
      loadingContinue: 'AIが引き続き回答を生成しています...',
      completed: lastMessage?.content
        ? `AIの回答：${lastMessage.content}`
        : 'AIの回答がありません。',
    },
  });

  return (
    <LayoutBody>
      <PageTitle title={`文章を生成${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div className='mx-auto p-6 max-w-(--page-width) lg:p-8'>
        <GenerateTextHeader />
        <Divider className='my-6' />
        <GenerateTextForm setFollowing={setFollowing} getGeneratedText={getGeneratedText} />
        <Divider className='my-3 lg:my-6' />
        <GenerateTextResult
          scrollableContainer={scrollableContainer}
          typingTextOutput={typingTextOutput}
          text={text}
        />
      </div>
      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {liveStatusMessage}
      </div>
    </LayoutBody>
  );
};
