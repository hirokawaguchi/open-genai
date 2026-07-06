import { useCallback, useEffect } from 'react';
import { useLocation } from 'react-router';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useChat } from '@/hooks/useChat';
import { useFiles } from '@/hooks/useFiles';
import { usePrompter } from '@/hooks/usePrompter';
import { useFileUploadable } from './useFileUploadable';

type UseChatReturn = ReturnType<typeof useChat>;

export const useChatSubmit = ({
  usecase,
  postChat,
  retryGeneration,
  updateSystemContext,
  getCurrentSystemContext,
  loading,
  setFollowing,
}: {
  usecase: string;
  postChat: UseChatReturn['postChat'];
  retryGeneration: UseChatReturn['retryGeneration'];
  updateSystemContext: UseChatReturn['updateSystemContext'];
  getCurrentSystemContext: UseChatReturn['getCurrentSystemContext'];
  loading: boolean;
  setFollowing: (following: boolean) => void;
}) => {
  const { content, setContent, inputSystemContext, shouldAutoSubmit, setShouldAutoSubmit } =
    useChatStore();

  const { clear: clearFiles, uploadedFiles, base64Cache } = useFiles(usecase);
  const { prompter } = usePrompter();
  const { fileUploadable } = useFileUploadable();
  const { state } = useLocation();

  const currentSystemContext = getCurrentSystemContext();

  const onSend = useCallback(() => {
    if (inputSystemContext !== currentSystemContext) {
      updateSystemContext(inputSystemContext);
    }
    setFollowing(true);
    postChat(prompter.chatPrompt({ content }), {
      uploadedFiles: fileUploadable ? uploadedFiles : undefined,
      base64Cache,
    });
    setContent('');
    clearFiles();
  }, [
    content,
    base64Cache,
    fileUploadable,
    setFollowing,
    inputSystemContext,
    updateSystemContext,
    currentSystemContext,
    prompter,
    postChat,
    uploadedFiles,
    setContent,
    clearFiles,
  ]);

  useEffect(() => {
    if (shouldAutoSubmit && content && inputSystemContext && !loading) {
      onSend();
      setShouldAutoSubmit(false);
      // リロード時に autoSubmit が再発火しないよう history state から autoSubmit を除去する
      // navigate ではなく replaceState を使い、React Router の再ナビゲーションを避ける
      if (state?.autoSubmit) {
        const { autoSubmit: _, ...rest } = state;
        window.history.replaceState(
          { ...(window.history.state ?? {}), usr: Object.keys(rest).length > 0 ? rest : undefined },
          '',
        );
      }
    }
  }, [shouldAutoSubmit, content, inputSystemContext, loading, onSend, setShouldAutoSubmit, state]);

  const onRetry = useCallback(() => {
    retryGeneration({ base64Cache });
  }, [retryGeneration, base64Cache]);

  return { onSend, onRetry };
};
