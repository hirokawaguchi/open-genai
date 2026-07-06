import { useCallback, useEffect } from 'react';
import { PageTitle } from '@/components/PageTitle';
import { Divider } from '@/components/ui/dads/Divider';
import { Switch } from '@/components/ui/Switch';
import { APP_TITLE } from '@/constants';
import { TranslateForm } from '@/features/translate/components/TranslateForm';
import { TranslateHeader } from '@/features/translate/components/TranslateHeader';
import { useReset } from '@/features/translate/hooks/useReset';
import { useSetDefaultValues } from '@/features/translate/hooks/useSetDefaultValues';
import { useTranslateStore } from '@/features/translate/stores/useTranslateStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { useLocalStorageBoolean } from '@/hooks/useLocalStorageBoolean';
import { usePrompter } from '@/hooks/usePrompter';
import { useTyping } from '@/hooks/useTyping';
import { LayoutBody } from '@/layout/LayoutBody';
import { debounce } from '@/utils/debounce';

export const TranslatePage = () => {
  const { sentence, additionalContext, language } = useTranslateStore();

  const { usecase, chatId } = useUsecasePath();
  const { loading, messages, postChat, clear } = useChat(usecase, chatId);

  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const translatedSentence = lastMessage?.role === 'assistant' ? lastMessage.content.trim() : '';

  const { typingTextOutput } = useTyping(loading, translatedSentence);
  const [auto, setAuto] = useLocalStorageBoolean('Auto_Translate', false);

  const { prompter } = usePrompter();

  useReset();

  useSetDefaultValues();

  // 文章の更新時にコメントを更新
  useEffect(() => {
    if (auto) {
      // debounce した後翻訳
      onSentenceChange(sentence, additionalContext, language, loading);
    }
  }, [sentence, language]);

  // debounce した後翻訳
  // 入力を止めて1秒ほど待ってから翻訳リクエストを送信
  const onSentenceChange = useCallback(
    debounce(
      (_sentence: string, _additionalContext: string, _language: string, _loading: boolean) => {
        if (_sentence === '') {
          clear();
        }

        if (_sentence !== '' && !_loading) {
          getTranslation(_sentence, _language, _additionalContext);
        }
      },
      1000,
    ),
    [prompter],
  );

  const getTranslation = (sentence: string, language: string, context: string) => {
    postChat(
      prompter.translatePrompt({
        sentence,
        language,
        context: context === '' ? undefined : context,
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
      <PageTitle title={`翻訳${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div className='mx-auto p-6 max-w-(--page-width) lg:p-8'>
        <TranslateHeader />
        <Divider className='my-6' />
        <Switch label='即時翻訳' checked={auto} onSwitch={setAuto} />
        <TranslateForm
          typingTextOutput={typingTextOutput}
          translatedSentence={translatedSentence}
          getTranslation={getTranslation}
        />
      </div>
      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {liveStatusMessage}
      </div>
    </LayoutBody>
  );
};
