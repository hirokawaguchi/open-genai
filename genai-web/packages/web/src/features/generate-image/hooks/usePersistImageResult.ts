import { useCallback } from 'react';
import { MAX_SAMPLE } from '@/features/generate-image/constants';
import { useGenerateImageStore } from '@/features/generate-image/stores/useGenerateImageStore';
import { saveImageResult } from '@/lib/chatApi';

export const usePersistImageResult = (chatId: string | undefined) => {
  const persistForMessage = useCallback(
    async (messageId: string) => {
      if (!chatId) {
        return;
      }

      const state = useGenerateImageStore.getState();
      const slots = state.image.slice(0, state.imageSample);
      if (slots.some((img) => img.error)) {
        return;
      }

      const images = slots.map((img) => img.base64).filter(Boolean);
      if (images.length === 0) {
        return;
      }

      await saveImageResult(chatId, messageId, {
        images,
        meta: {
          prompt: state.prompt,
          negativePrompt: state.negativePrompt,
          stylePreset: state.stylePreset,
          seeds: state.seed.slice(0, MAX_SAMPLE),
          step: state.step,
          cfgScale: state.cfgScale,
          imageSample: state.imageSample,
        },
      });
    },
    [chatId],
  );

  return { persistForMessage };
};
