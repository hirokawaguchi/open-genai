import type { ShownMessage } from 'genai-web';
import { useEffect, useRef } from 'react';
import { MAX_SAMPLE } from '@/features/generate-image/constants';
import { useGenerateImageStore } from '@/features/generate-image/stores/useGenerateImageStore';
import {
  fileUrlToBase64,
  findLatestImageResultMessage,
} from '@/features/generate-image/utils/imageResultExtraData';

export const useRestoreImageFromHistory = (
  chatId: string | undefined,
  rawMessages: ShownMessage[],
  loadingMessages: boolean,
) => {
  const restoredChatIdRef = useRef<string | null>(null);
  const {
    setPrompt,
    setNegativePrompt,
    setStylePreset,
    setSeed,
    setStep,
    setCfgScale,
    setImageSample,
    setImage,
    clearImage,
  } = useGenerateImageStore();

  useEffect(() => {
    if (!chatId || loadingMessages) {
      if (!chatId) {
        restoredChatIdRef.current = null;
      }
      return;
    }

    if (restoredChatIdRef.current === chatId) {
      return;
    }

    const latest = findLatestImageResultMessage(rawMessages);
    if (!latest) {
      restoredChatIdRef.current = chatId;
      return;
    }

    let cancelled = false;

    const restore = async () => {
      clearImage();
      setPrompt(latest.result.prompt);
      setNegativePrompt(latest.result.negativePrompt);
      setStylePreset(latest.result.stylePreset);
      setStep(latest.result.step);
      setCfgScale(latest.result.cfgScale);
      setImageSample(latest.result.imageSample);

      latest.result.seeds.forEach((seed, index) => {
        if (index < MAX_SAMPLE) {
          setSeed(seed, index);
        }
      });

      const results = await Promise.allSettled(
        latest.result.images.map((img) => fileUrlToBase64(img.fileUrl)),
      );

      if (cancelled) {
        return;
      }

      results.forEach((res, index) => {
        if (res.status === 'fulfilled' && res.value) {
          setImage(index, res.value);
        }
      });

      restoredChatIdRef.current = chatId;
    };

    restore();

    return () => {
      cancelled = true;
    };
  }, [
    chatId,
    loadingMessages,
    rawMessages,
    clearImage,
    setPrompt,
    setNegativePrompt,
    setStylePreset,
    setSeed,
    setStep,
    setCfgScale,
    setImageSample,
    setImage,
  ]);
};
