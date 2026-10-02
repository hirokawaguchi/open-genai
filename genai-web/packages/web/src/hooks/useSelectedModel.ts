import { useEffect } from 'react';
import useSWR from 'swr';
import { useLocalStorage } from '@/hooks/useLocalStorage';
import { teamApiFetcher } from '@/lib/fetcher';
import {
  availableTextModelIds,
  MODEL_ID_STORAGE_KEY,
  resolveSelectedModelId,
  setAllowedModelFilter,
} from '@/models';

type AllowedModels = {
  unrestricted?: boolean;
  models?: string[];
};

export const useSelectedModel = () => {
  const [modelId, setModelId] = useLocalStorage(MODEL_ID_STORAGE_KEY, '');
  const { data } = useSWR<AllowedModels>('models/allowed', teamApiFetcher, {
    shouldRetryOnError: false,
  });

  if (data) {
    setAllowedModelFilter(data.unrestricted ? null : (data.models ?? []));
  }

  useEffect(() => {
    if (!data) {
      return;
    }
    const resolved = resolveSelectedModelId();
    if (resolved && modelId !== resolved) {
      setModelId(resolved);
    }
  }, [data, modelId, setModelId]);

  const availableModelIds = availableTextModelIds();
  const selectedModelId =
    modelId && availableModelIds.includes(modelId) ? modelId : (resolveSelectedModelId() ?? '');

  return {
    selectedModelId,
    availableModelIds,
    setSelectedModelId: (id: string) => {
      setModelId(id);
    },
  };
};
