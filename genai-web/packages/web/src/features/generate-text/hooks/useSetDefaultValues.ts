import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { MODELS } from '@/models';
import { useGenerateTextStore } from '../stores/useGenerateTextStore';
import { GenerateTextPageQueryParams } from '../types';

export const useSetDefaultValues = () => {
  const { search } = useLocation();
  const { setInformation, setContext } = useGenerateTextStore();
  const { usecase, chatId } = useUsecasePath();
  const { getModelId, setModelId } = useChat(usecase, chatId);
  const { modelIds: availableModels } = MODELS;

  useEffect(() => {
    const modelId = getModelId();
    const defaultModelId = !modelId ? availableModels[0] : modelId;

    if (search !== '') {
      const params = Object.fromEntries(new URLSearchParams(search)) as GenerateTextPageQueryParams;
      setInformation(params.information ?? '');
      setContext(params.context ?? '');

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
