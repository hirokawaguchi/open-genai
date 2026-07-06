import type { SystemContext } from 'genai-web';
import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router';
import { TOP_CHAT_SYSTEM_PROMPT, TOP_CHAT_SYSTEM_PROMPT_TITLE } from '@/features/landing/constants';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { MODELS } from '@/models';
import { useChatStore } from '../stores/useChatStore';
import { ChatPageQueryParams } from '../types';

interface LocationState {
  content?: string;
  systemContext?: string;
  systemContextTitle?: string;
  autoSubmit?: boolean;
}

export const useSetDefaultValues = (systemContextList: SystemContext[]) => {
  const {
    setContent,
    setInputSystemContext,
    setSystemContextTitle,
    setShouldAutoSubmit,
    setHasSent,
  } = useChatStore();
  const { search, state } = useLocation();
  const { usecase, chatId } = useUsecasePath();
  const { getModelId, setModelId, clear, getCurrentSystemContext, updateSystemContext } = useChat(
    usecase,
    chatId,
  );
  const { modelIds: availableModels } = MODELS;
  const modelId = getModelId();

  // state は初回のナビゲーション時のみ有効。
  // ハッシュリンクや戻る/進むボタンで state が失われても再処理しないようにする。
  const hasProcessedStateRef = useRef(false);
  const prevChatIdRef = useRef(chatId);

  useEffect(() => {
    // chatId が変わったら hasProcessedStateRef をリセット
    if (prevChatIdRef.current !== chatId) {
      hasProcessedStateRef.current = false;
      prevChatIdRef.current = chatId;
    }
    const defaultModelId = !modelId ? availableModels[0] : modelId;
    const locationState = state as LocationState | undefined;

    // state が処理済みで、かつ state が失われた場合はスキップ
    // （左メニューのクリック、ハッシュリンク、戻る/進むボタンで state が undefined になる）
    if (hasProcessedStateRef.current && !state && search === '') {
      return;
    }

    if (search === '' && !state) {
      setContent('');
      setModelId(defaultModelId);
      setShouldAutoSubmit(false);
      setHasSent(false);
      hasProcessedStateRef.current = false;
      return;
    }

    // state が存在する場合は処理済みとしてマーク
    if (state) {
      hasProcessedStateRef.current = true;
    }

    const params = Object.fromEntries(new URLSearchParams(search)) as ChatPageQueryParams;

    // state または query params から content と systemContext を取得
    const content = locationState?.content ?? params.content ?? '';
    const systemContext = locationState?.systemContext ?? params.systemContext;
    const autoSubmit = locationState?.autoSubmit ?? params.autoSubmit === 'true';

    if (systemContext && systemContext !== '') {
      updateSystemContext(systemContext);
      setInputSystemContext(systemContext);
      setSystemContextTitle(locationState?.systemContextTitle ?? '');
    } else {
      clear();
      setInputSystemContext(getCurrentSystemContext());
    }

    setContent(content);
    setModelId(availableModels.includes(params.modelId ?? '') ? params.modelId! : defaultModelId);
    const shouldSubmit = autoSubmit && !!content.trim();
    setShouldAutoSubmit(shouldSubmit);
    setHasSent(shouldSubmit);
  }, [search, state, chatId]);

  // 既存チャット遷移時にシステムプロンプトタイトルを解決
  const currentSystemContext = getCurrentSystemContext();
  const prevChatIdForTitleRef = useRef(chatId);
  useEffect(() => {
    const prevChatId = prevChatIdForTitleRef.current;
    prevChatIdForTitleRef.current = chatId;

    // 既存チャット → 新規チャットへの遷移時はタイトルをクリア
    if (!chatId) {
      if (prevChatId) {
        setSystemContextTitle('');
      }
      return;
    }

    // chatId が変わった場合（chat-1→chat-2）、restore 完了前は
    // currentSystemContext が空のため、前チャットのタイトルが残らないようクリア
    if (prevChatId !== chatId) {
      setSystemContextTitle('');
    }

    if (!currentSystemContext) {
      return;
    }

    const trimmed = currentSystemContext.trim();

    if (TOP_CHAT_SYSTEM_PROMPT && trimmed === TOP_CHAT_SYSTEM_PROMPT.trim()) {
      setSystemContextTitle(TOP_CHAT_SYSTEM_PROMPT_TITLE);
      return;
    }

    const matched = systemContextList.find((item) => item.systemContext.trim() === trimmed);
    setSystemContextTitle(matched?.systemContextTitle ?? '');
  }, [chatId, currentSystemContext, systemContextList, setSystemContextTitle]);
};
