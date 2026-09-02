import { useEffect } from 'react';
import { useLocalStorage } from '@/hooks/useLocalStorage';
import { MODEL_ID_STORAGE_KEY, MODELS, resolveSelectedModelId } from '@/models';

export const useSelectedModel = () => {
  const [modelId, setModelId] = useLocalStorage(MODEL_ID_STORAGE_KEY, '');
  const { modelIds: availableModels } = MODELS;

  useEffect(() => {
    const resolved = resolveSelectedModelId();
    if (resolved && modelId !== resolved) {
      setModelId(resolved);
    }
  }, [modelId, setModelId]);

  const selectedModelId =
    modelId && availableModels.includes(modelId) ? modelId : (resolveSelectedModelId() ?? '');

  return {
    selectedModelId,
    setSelectedModelId: (id: string) => {
      setModelId(id);
    },
  };
};
