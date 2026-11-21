import { useCallback, useEffect } from 'react';
import { useLocation } from 'react-router';
import { formatKnowledgeContext, searchKnowledge } from '@/features/chat/knowledgeSearch';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { formatWebSearchContext, searchWeb } from '@/features/chat/webSearch';
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
  messages,
}: {
  usecase: string;
  postChat: UseChatReturn['postChat'];
  retryGeneration: UseChatReturn['retryGeneration'];
  updateSystemContext: UseChatReturn['updateSystemContext'];
  getCurrentSystemContext: UseChatReturn['getCurrentSystemContext'];
  loading: boolean;
  setFollowing: (following: boolean) => void;
  messages?: { role: string; content: string }[];
}) => {
  const { content, setContent, inputSystemContext, shouldAutoSubmit, setShouldAutoSubmit } =
    useChatStore();

  const { clear: clearFiles, uploadedFiles, base64Cache } = useFiles(usecase);
  const { prompter } = usePrompter();
  const { fileUploadable } = useFileUploadable();
  const { state } = useLocation();

  const currentSystemContext = getCurrentSystemContext();

  const onSend = useCallback(
    (overrideContent?: string) => {
      if (inputSystemContext !== currentSystemContext) {
        updateSystemContext(inputSystemContext);
      }
      setFollowing(true);
      const text = (overrideContent ?? useChatStore.getState().content) || content;
      const picks = useChatStore.getState().knowledgePicks;
      const webSearchOn = useChatStore.getState().webSearchOn;
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
        let webSearchContext: string | undefined;
        if (webSearchOn) {
          useChatStore.getState().setWebSearching(true);
          try {
            // 直近の会話を渡し、サーバ側で文脈を踏まえた検索クエリに言い換える。
            const history = (messages ?? [])
              .slice(-6)
              .map((m) => ({ role: m.role, content: m.content }));
            const found = await searchWeb(text, history);
            webSearchContext = formatWebSearchContext(found.passages ?? []);
          } catch (e: unknown) {
            window.alert(`Web 検索に失敗しました: ${errorText(e)}`);
            return;
          } finally {
            useChatStore.getState().setWebSearching(false);
          }
        }
        void Promise.resolve(
          postChat(prompter.chatPrompt({ content: text }), {
            uploadedFiles: fileUploadable ? uploadedFiles : undefined,
            base64Cache,
            knowledgeContext,
            webSearchContext,
          }),
        ).catch((e: unknown) => {
          window.alert(`送信に失敗しました: ${errorText(e)}`);
        });
        setContent('');
        clearFiles();
      };
      void send();
    },
    [
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
      messages,
    ],
  );

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
    const webSearchOn = useChatStore.getState().webSearchOn;
    if (!webSearchOn) {
      retryGeneration({ base64Cache });
      return;
    }
    // スイッチがオンなら、直前のユーザー発話で検索し直してから再生成する。
    const lastUserIdx = (messages ?? []).map((m) => m.role).lastIndexOf('user');
    const text = ((messages ?? [])[lastUserIdx]?.content ?? '').trim();
    if (!text) {
      retryGeneration({ base64Cache });
      return;
    }
    void (async () => {
      let webSearchContext: string | undefined;
      useChatStore.getState().setWebSearching(true);
      try {
        // 直前のユーザー発話より前の会話を文脈として渡す。
        const history = (messages ?? [])
          .slice(0, Math.max(lastUserIdx, 0))
          .slice(-6)
          .map((m) => ({ role: m.role, content: m.content }));
        const found = await searchWeb(text, history);
        webSearchContext = formatWebSearchContext(found.passages ?? []);
      } catch (e: unknown) {
        window.alert(`Web 検索に失敗しました: ${errorText(e)}`);
        return;
      } finally {
        useChatStore.getState().setWebSearching(false);
      }
      retryGeneration({ base64Cache, webSearchContext });
    })();
  }, [retryGeneration, base64Cache, messages]);

  return { onSend, onRetry };
};
