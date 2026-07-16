import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { SupportText } from '@/components/ui/dads/SupportText';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { ChatNotificationDialog } from '@/features/chat/components/ChatNotificationDialog';
import { ChatNotificationDialogButton } from '@/features/chat/components/ChatNotificationDialogButton';
import { ModelSelector } from '@/features/landing/components/ModelSelector';
import { TOP_CHAT_SYSTEM_PROMPT, TOP_CHAT_SYSTEM_PROMPT_TITLE } from '@/features/landing/constants';
import { LandingChatFormSchema, landingChatFormSchema } from '@/features/landing/schema';
import { requestSubmitOnEnter, submitKeyHint } from '@/utils/keyboard';

export const LandingForm = () => {
  const navigate = useNavigate();
  const [isNotificationDialogOpen, setIsNotificationDialogOpen] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LandingChatFormSchema>({
    resolver: zodResolver(landingChatFormSchema),
  });

  const onSubmit = handleSubmit((data) => {
    navigate('/chat', {
      state: {
        content: data.chatInput,
        systemContext: TOP_CHAT_SYSTEM_PROMPT,
        systemContextTitle: TOP_CHAT_SYSTEM_PROMPT_TITLE,
        autoSubmit: true,
      },
    });
  });

  return (
    <div className='mt-8 lg:mt-10'>
      <h2 id='landing-chat-input-heading' className='mb-2 text-std-20B-160'>
        お手伝いできることはありますか？お気軽にご相談ください
        <span className='text-std-16N-170'>（送信したらチャット画面に遷移します）</span>
      </h2>
      <form onSubmit={onSubmit}>
        <div className='flex flex-col gap-4'>
          <SupportText id='chat-input-support'>
            例）"国会答弁を検索したい"、"法制度について詳しく調べたい"、"引き継ぎ作業をやりたいので適切なプロンプトを考えて"
          </SupportText>
          <div className='flex items-center gap-4 lg:gap-6'>
            <ModelSelector />
            <ChatNotificationDialogButton onClick={() => setIsNotificationDialogOpen(true)} />
          </div>
          <AutoResizeTextarea
            id='chat-input'
            aria-labelledby='landing-chat-input-heading'
            aria-describedby={
              errors.chatInput
                ? 'chat-input-support chat-input-submit-hint chat-input-error'
                : 'chat-input-support chat-input-submit-hint'
            }
            aria-invalid={errors.chatInput ? true : undefined}
            required
            rows={3}
            onKeyDown={requestSubmitOnEnter}
            {...register('chatInput')}
          />
          <SupportText id='chat-input-submit-hint'>{submitKeyHint}</SupportText>
          <div className='flex justify-end'>
            {errors.chatInput && (
              <ErrorText className='mr-auto -mt-1' id='chat-input-error'>
                ＊{errors.chatInput.message}
              </ErrorText>
            )}
            <Button
              type='submit'
              size='md'
              variant='solid-fill'
              className='inline-flex justify-center items-center gap-1'
            >
              <SendIcon aria-hidden={true} className='shrink-0' />
              送信
            </Button>
          </div>
        </div>
      </form>
      <ChatNotificationDialog
        isOpen={isNotificationDialogOpen}
        onClose={() => setIsNotificationDialogOpen(false)}
      />
    </div>
  );
};
