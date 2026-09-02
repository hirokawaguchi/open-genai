import { CRI_PREFIX_PATTERN, modelMetadata } from '@genai-web/common';
import type { Model } from 'genai-web';

const bedrockModelIds: string[] = (JSON.parse(import.meta.env.VITE_APP_MODEL_IDS) as string[])
  .map((name: string) => name.trim())
  .filter((name: string) => name);

const duplicateBaseModelIds = new Set(
  bedrockModelIds
    .map((modelId) => modelId.replace(CRI_PREFIX_PATTERN, ''))
    .filter((item, index, arr) => arr.indexOf(item) !== index),
);
const endpointNames: string[] = JSON.parse(import.meta.env.VITE_APP_ENDPOINT_NAMES)
  .map((name: string) => name.trim())
  .filter((name: string) => name);

const imageGenModelIds: string[] = (
  JSON.parse(import.meta.env.VITE_APP_IMAGE_MODEL_IDS) as string[]
)
  .map((name: string) => name.trim())
  .filter((name: string) => name);

const textModels = [
  ...bedrockModelIds.map((name) => ({ modelId: name, type: 'bedrock' }) as Model),
  ...endpointNames.map((name) => ({ modelId: name, type: 'sagemaker' }) as Model),
];
const imageGenModels = [
  ...imageGenModelIds.map((name) => ({ modelId: name, type: 'bedrock' }) as Model),
];

export const MODEL_ID_STORAGE_KEY = 'modelId_v20260218';

export const availableTextModelIds = (): string[] => [...bedrockModelIds, ...endpointNames];

export const findModelByModelId = (modelId: string) => {
  const model = textModels.find((m) => m.modelId === modelId);
  if (!model) {
    return undefined;
  }
  return { ...model };
};

/**
 * 画面の選択と送信で同じ ID を使う。
 * ビルドでモデル一覧が変わって localStorage が古い場合は、有効な先頭 ID に書き戻す。
 */
export const resolveSelectedModelId = (): string | undefined => {
  const available = availableTextModelIds();
  const stored = localStorage.getItem(MODEL_ID_STORAGE_KEY) ?? '';
  if (stored && available.includes(stored)) {
    return stored;
  }
  const fallback = available[0];
  if (fallback && stored !== fallback) {
    localStorage.setItem(MODEL_ID_STORAGE_KEY, fallback);
  }
  return fallback;
};

export const resolveSelectedModel = (): Model | undefined => {
  const id = resolveSelectedModelId();
  return id ? findModelByModelId(id) : undefined;
};

export const findModelDisplayNameByModelId = (modelId: string): string => {
  let displayName = modelMetadata[modelId]?.displayName ?? modelId;
  if (duplicateBaseModelIds.has(modelId.replace(CRI_PREFIX_PATTERN, ''))) {
    const matched = modelId.match(CRI_PREFIX_PATTERN);
    if (matched) {
      displayName += ` (${matched[1].toUpperCase()})`;
    }
  }
  return displayName;
};

export const MODELS = {
  modelIds: [...bedrockModelIds, ...endpointNames],
  modelMetadata,
  imageGenModelIds: imageGenModelIds,
  imageGenModels: imageGenModels,
};
