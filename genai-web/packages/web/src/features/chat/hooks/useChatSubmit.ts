import { useCallback, useEffect } from 'react';
import { useLocation } from 'react-router';
import { formatKnowledgeContext, searchKnowledge } from '@/features/chat/knowledgeSearch';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useChat } from '@/hooks/useChat';
import { useFiles } from '@/hooks/useFiles';
import { usePrompter } from '@/hooks/usePrompter';
import { useFileUploadable } from './useFileUploadable';

type UseChatReturn = ReturnType<typeof useChat>;

const errorText = (e: unknown) => {
  if (typeof e === 'object' && e !== null && 'response' in e) {
    const data = (e as { response?: { data?: { error?: unknown } } }).response?.data;
    if (typeof data?.error === 'string' && data.error) {
      return data.error;
    }
  }
  return e instanceof Error ? e.message : String(e);
};

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

  const onSend = useCallback((overrideContent?: string) => {
    if (inputSystemContext !== currentSystemContext) {
      updateSystemContext(inputSystemContext);
    }
    setFollowing(true);
    const text = (overrideContent ?? useChatStore.getState().content) || content;
    const picks = useChatStore.getState().knowledgePicks;
    const send = async () => {
      let knowledgeContext: string | undefined;
      if (picks.length > 0) {
        useChatStore.getState().setKnowledgeSearching(true);
        try {
          const found = await searchKnowledge(text, picks);
          knowledgeContext = formatKnowledgeContext(found.passages ?? []);
        } catch (e: unknown) {
          window.alert(`ナレッジの検索に失敗しました: ${errorText(e)}`);
          return;
        } finally {
          useChatStore.getState().setKnowledgeSearching(false);
        }
      }
      void Promise.resolve(
        postChat(prompter.chatPrompt({ content: text }), {
          uploadedFiles: fileUploadable ? uploadedFiles : undefined,
          base64Cache,
          knowledgeContext,
        }),
      ).catch((e: unknown) => {
        window.alert(`送信に失敗しました: ${errorText(e)}`);
      });
      setContent('');
      clearFiles();
    };
    void send();
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
