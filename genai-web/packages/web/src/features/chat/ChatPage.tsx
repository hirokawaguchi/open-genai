import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { APP_TITLE } from '@/constants';
import { ChatHints } from '@/features/chat/components/ChatHints';
import { ChatHistorySidebar } from '@/features/chat/components/ChatHistorySidebar';
import { ChatInput } from '@/features/chat/components/ChatInput';
import { ChatMessage } from '@/features/chat/components/ChatMessage';
import { ChatNotificationDialog } from '@/features/chat/components/ChatNotificationDialog';
import { ChatStickyHeader } from '@/features/chat/components/ChatStickyHeader';
import { DialogPromptList } from '@/features/chat/components/DialogPromptList';
import { DialogSaveSystemContext } from '@/features/chat/components/DialogSaveSystemContext';
import { FileDrop } from '@/features/chat/components/FileDrop';
import { Title } from '@/features/chat/components/Title';
import { useChatAnnouncementDelay } from '@/features/chat/hooks/useChatAnnouncementDelay';
import { useChatSubmit } from '@/features/chat/hooks/useChatSubmit';
import { useChatTitle } from '@/features/chat/hooks/useChatTitle';
import { useFileUploadable } from '@/features/chat/hooks/useFileUploadable';
import { useReset } from '@/features/chat/hooks/useReset';
import { useSetDefaultValues } from '@/features/chat/hooks/useSetDefaultValues';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useFollow } from '@/hooks/useFollow';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { useScreen } from '@/hooks/useScreen';
import { useSystemContext } from './hooks/useSystemContext';
import { ChatPageQueryParams } from './types';

export const ChatPage = () => {
  const {
    setContent,
    saveSystemContext,
    setInputSystemContext,
    setSystemContextTitle,
    setIsDragOver,
    shouldAutoSubmit,
    setHasSent,
  } = useChatStore();

  const { pathname, search, state } = useLocation();
  const { usecase, chatId } = useUsecasePath();
  const navigate = useNavigate();
  const { scrollTopAnchorRef, scrollBottomAnchorRef } = useScreen({
    useWindowScroll: true,
  });

  const [showSystemContextDialog, setShowSystemContextDialog] = useState(false);
  const [showPromptListDialog, setShowPromptListDialog] = useState(false);
  const [isNotificationDialogOpen, setIsNotificationDialogOpen] = useState(false);
  const { systemContextList, onSaveSystemContext, onDeleteSystemContext, onUpdateSystemContext } =
    useSystemContext();

  const {
    loading,
    loadingMessages,
    isEmpty,
    messages,
    clear,
    postChat,
    updateSystemContext,
    getCurrentSystemContext,
    retryGeneration,
    chatTitle,
  } = useChat(usecase, chatId);

  const { scrollableContainer, setFollowing } = useFollow();

  useReset();

  // 履歴を持つチャットのメッセージ読み込み完了時に最下部へスクロール
  useEffect(() => {
    if (chatId && !loadingMessages && !isEmpty) {
      setFollowing(true);
    }
  }, [chatId, loadingMessages, isEmpty, setFollowing]);

  // 画面遷移時に出力が残る問題の対応
  // メッセージが空の時はテキストをクリア（自動送信時・クエリパラメータ指定時は除く）
  useEffect(() => {
    if (messages.length === 0 && !shouldAutoSubmit && search === '') {
      setContent('');
    }
  }, [messages, setContent, shouldAutoSubmit, search]);

  const { title } = useChatTitle(chatTitle);

  const { accept, fileUploadable } = useFileUploadable();

  useSetDefaultValues(systemContextList);

  const currentSystemContext = getCurrentSystemContext();

  const { onSend, onRetry } = useChatSubmit({
    usecase,
    postChat,
    retryGeneration,
    updateSystemContext,
    getCurrentSystemContext,
    loading,
    setFollowing,
  });

  const onReset = useCallback(() => {
    clear();
    setContent('');
    setSystemContextTitle('');
    setHasSent(false);
  }, [clear, setSystemContextTitle, setHasSent, setContent]);

  const onNewChat = useCallback(() => {
    onReset();
    navigate('/chat', { state: { shouldReset: true } });
    document.getElementById('window-title')?.focus();
  }, [navigate, onReset]);

  useEffect(() => {
    // URLにクエリパラメータがある場合は useSetDefaultValues に任せる
    if (search !== '') {
      return;
    }
    // state に systemContext が含まれる場合は useSetDefaultValues に任せる（トップチャットからの遷移等）
    if (state?.systemContext) {
      return;
    }
    setInputSystemContext(currentSystemContext);
  }, [currentSystemContext, setInputSystemContext, search, state]);

  const onClickSamplePrompt = (params: ChatPageQueryParams) => {
    setContent(params.content ?? '');
    updateSystemContext(params.systemContext ?? '');
  };

  const handleDragOver = (event: React.DragEvent) => {
    // ファイルドラッグ時にオーバーレイを表示
    event.preventDefault();
    setIsDragOver(true);
  };

  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;

  const { announcementDelay } = useChatAnnouncementDelay({
    isFromTopChat: !!state?.autoSubmit,
    loading,
    isEmpty,
  });

  const { liveStatusMessage } = useLiveStatusMessage({
    active: lastMessage?.role === 'assistant' || loading,
    loading: loading,
    startDelay: announcementDelay,
    messages: {
      loading: 'AIが回答を生成しています...',
      loadingContinue: 'AIが引き続き回答を生成しています...',
      completed: lastMessage?.content
        ? `AIの回答：${lastMessage.content}`
        : 'AIの回答がありません。',
    },
  });

  return (
    <>
      <PageTitle title={`${title}${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div
        onDragOver={fileUploadable ? handleDragOver : undefined}
        className='relative mx-auto grid grid-cols-1 grid-rows-[auto_1fr] max-w-(--page-width) min-h-[calc(100vh-var(--header-height))] pt-6 px-6 lg:px-8 lg:pt-8'
      >
        <div className='lg:mb-3.5'>
          <BreadcrumbsNav
            items={
              chatId
                ? [
                    { label: 'ホーム', to: '/' },
                    { label: 'チャット', to: '/chat' },
                    { label: title },
                  ]
                : [{ label: 'ホーム', to: '/' }, { label: 'チャット' }]
            }
            className='mb-4'
          />
          <div className='flex flex-wrap min-h-[calc(38/16*1rem)] justify-between items-start gap-x-2 gap-y-4'>
            <Title title={title} />
            {!isEmpty && !loadingMessages && (
              <Button
                variant='solid-fill'
                size='md'
                className='-mt-1 text-nowrap lg:hidden'
                onClick={onNewChat}
              >
                新規チャット
              </Button>
            )}
          </div>
        </div>

        <div className='flex justify-between gap-10 xl:gap-16'>
          <div className='flex min-w-0 flex-1 max-w-[calc(1056/16*1rem)] flex-col'>
            <ChatStickyHeader
              title={title}
              currentSystemContext={currentSystemContext}
              onOpenNotificationDialog={() => setIsNotificationDialogOpen(true)}
              onOpenSystemContextDialog={() => setShowSystemContextDialog(true)}
              onOpenPromptListDialog={() => setShowPromptListDialog(true)}
            />

            <div className='flex-1 py-4 px-2 lg:pb-6'>
              <div ref={scrollTopAnchorRef} />

              {loadingMessages && (
                <div className='relative grid min-h-[50vh] w-full place-content-center'>
                  <ProgressIndicator isLarge={true} label='読み込み中...' />
                </div>
              )}

              {isEmpty && !loadingMessages && (
                <div className='w-full py-4'>
                  <ChatHints />
                </div>
              )}

              <div ref={scrollableContainer} className='flex flex-col gap-4'>
                {!isEmpty &&
                  messages.map((chat, idx) => (
                    <ChatMessage
                      key={chat.messageId ?? `message-${idx}`}
                      chatContent={chat}
                      loading={loading && idx === messages.length - 1}
                      allowRetry={idx === messages.length - 1}
                      retryGeneration={onRetry}
                    />
                  ))}
              </div>

              <div ref={scrollBottomAnchorRef} />
            </div>

            <div className='sticky bottom-0 z-1'>
              <ChatInput onSend={onSend} fileUpload={fileUploadable} accept={accept} />
            </div>
          </div>

          <div className='hidden shrink-0 lg:block lg:w-56 xl:w-64'>
            <div className='sticky top-[calc(var(--header-height))] -mt-4 pt-4 pb-2'>
              <div className='grid grid-cols-1 grid-rows-[auto_1fr] max-h-[calc(100vh-var(--header-height)-1.5rem)] gap-6'>
                <Button variant='solid-fill' size='lg' className='w-full' onClick={onNewChat}>
                  新規チャット
                </Button>
                <ChatHistorySidebar />
              </div>
            </div>
          </div>
        </div>
      </div>

      <FileDrop fileUpload={fileUploadable} accept={accept} />

      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {liveStatusMessage}
      </div>

      <DialogSaveSystemContext
        isOpen={showSystemContextDialog}
        systemContext={saveSystemContext}
        onClose={() => setShowSystemContextDialog(false)}
        onSave={async (title, systemContext, options) => {
          try {
            await onSaveSystemContext(title, systemContext, options);
            setSystemContextTitle(title);
          } catch (e) {
            console.error(e);
          }
        }}
      />

      <DialogPromptList
        isOpen={showPromptListDialog}
        onClick={onClickSamplePrompt}
        systemContextList={systemContextList}
        onClickDeleteSystemContext={onDeleteSystemContext}
        onClickUpdateSystemContext={onUpdateSystemContext}
        onClose={() => setShowPromptListDialog(false)}
      />

      <ChatNotificationDialog
        isOpen={isNotificationDialogOpen}
        onClose={() => setIsNotificationDialogOpen(false)}
      />
    </>
  );
};
