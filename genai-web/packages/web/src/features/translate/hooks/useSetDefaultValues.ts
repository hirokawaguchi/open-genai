import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { MODELS } from '@/models';
import { LANGUAGES } from '../constants';
import { useTranslateStore } from '../stores/useTranslateStore';
import { TranslatePageQueryParams } from '../types';

export const useSetDefaultValues = () => {
  const { search } = useLocation();
  const { setSentence, setAdditionalContext, setLanguage } = useTranslateStore();
  const { usecase, chatId } = useUsecasePath();
  const { getModelId, setModelId } = useChat(usecase, chatId);
  const { modelIds: availableModels } = MODELS;

  useEffect(() => {
    const modelId = getModelId();
    const defaultModelId = !modelId ? availableModels[0] : modelId;

    if (search !== '') {
      const params = Object.fromEntries(new URLSearchParams(search)) as TranslatePageQueryParams;
      setSentence(params.sentence ?? '');
      setAdditionalContext(params.additionalContext ?? '');
      setLanguage(params.language || LANGUAGES[0]);
      const nextModelId = availableModels.includes(params.modelId ?? '')
        ? params.modelId!
        : defaultModelId;
      if (nextModelId) {
        setModelId(nextModelId);
      }
    } else if (defaultModelId) {
      setModelId(defaultModelId);
    }
  }, [search]);
};
