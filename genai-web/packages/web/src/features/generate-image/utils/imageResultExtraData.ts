import type { ExtraData, ShownMessage } from 'genai-web';

export const IMAGE_RESULT_EXTRA_NAME = 'open-genai-generated-image';

export type StoredImageGenResult = {
  version: number;
  prompt: string;
  negativePrompt: string;
  stylePreset: string;
  seeds: number[];
  step: number;
  cfgScale: number;
  imageSample: number;
  images: { fileUrl: string }[];
};

export const parseImageResultExtraData = (
  extraData: ExtraData[] | undefined,
): StoredImageGenResult | null => {
  if (!extraData?.length) {
    return null;
  }
  const entry = extraData.find((e) => e.name === IMAGE_RESULT_EXTRA_NAME);
  if (!entry || entry.source.type !== 'json') {
    return null;
  }
  try {
    return JSON.parse(entry.source.data) as StoredImageGenResult;
  } catch {
    return null;
  }
};

export const findLatestImageResultMessage = (
  messages: ShownMessage[],
): { messageId: string; result: StoredImageGenResult } | null => {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== 'assistant' || !m.messageId) {
      continue;
    }
    const result = parseImageResultExtraData(m.extraData);
    if (result?.images?.length) {
      return { messageId: m.messageId, result };
    }
  }
  return null;
};

export const fileUrlToBase64 = async (fileUrl: string): Promise<string> => {
  const res = await fetch(fileUrl);
  if (!res.ok) {
    throw new Error(`failed to fetch image (${res.status})`);
  }
  const blob = await res.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = reader.result as string;
      resolve(dataUrl.includes(',') ? dataUrl.split(',', 2)[1] : dataUrl);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
};
