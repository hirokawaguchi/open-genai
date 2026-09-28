import type { GenerateImageParams } from 'genai-web';
import { useGenerateImage } from '@/features/generate-image/hooks/useGenerateImage';
import { useGenerateImageStore } from '@/features/generate-image/stores/useGenerateImageStore';
import type { ApiError } from '@/lib/fetcher';
import { MODELS } from '@/models';
import { AMAZON_ADVANCED_GENERATION_MODE, GENERATION_MODES, MODEL_INFO } from '../constants';
import { formatLocalSdUnavailableMessage } from '../utils/formatLocalSdUnavailable';
import { generateRandomSeed } from '../utils/generateRandomSeed';

type UseGenerateImageHandlerReturn = {
  handleGenerateImage: (
    prompt: string,
    negativePrompt: string,
    stylePreset?: string,
  ) => Promise<void>;
  onClickRandomSeed: (selectedImageIndex: number) => void;
};

export const useGenerateImageHandler = (
  setGenerating: (generating: boolean) => void,
): UseGenerateImageHandlerReturn => {
  const {
    imageGenModelId,
    resolution,
    stylePreset,
    seed,
    setSeed,
    step,
    cfgScale,
    generationMode,
    initImage,
    maskImage,
    maskPrompt,
    colors,
    setImage,
    setImageError,
    clearImage,
    imageSample,
    imageStrength,
    controlStrength,
    controlMode,
  } = useGenerateImageStore();

  const { generateImage } = useGenerateImage();
  const { imageGenModels, imageGenModelIds } = MODELS;

  const [width, height] = resolution.label.split('x').map((v) => Number(v));

  const handleGenerateImage = async (
    _prompt: string,
    _negativePrompt: string,
    _stylePreset?: string,
  ) => {
    clearImage();
    setGenerating(true);

    const modelConfig = MODEL_INFO[imageGenModelId];
    if (!modelConfig) {
      console.error(`Unknown model: ${imageGenModelId}`);
      setGenerating(false);
      return;
    }

    const promises = new Array(imageSample).fill('').map((_, idx) => {
      let _seed = seed[idx];
      if (_seed < 0) {
        const rand = generateRandomSeed();
        setSeed(rand, idx);
        _seed = rand;
      }

      let params: GenerateImageParams = {
        textPrompt: [
          {
            text: _prompt,
            weight: 1,
          },
          {
            text: _negativePrompt,
            weight: -1,
          },
        ],
        width: width,
        height: height,
        cfgScale,
        seed: _seed,
        step,
        stylePreset: _stylePreset ?? stylePreset,
        taskType: generationMode === 'IMAGE_CONDITIONING' ? 'TEXT_IMAGE' : generationMode,
      };

      if (generationMode === GENERATION_MODES.IMAGE_VARIATION) {
        params = {
          ...params,
          initImage: initImage.imageBase64,
          imageStrength,
        };
      } else if (
        generationMode === GENERATION_MODES.INPAINTING ||
        generationMode === GENERATION_MODES.OUTPAINTING
      ) {
        params = {
          ...params,
          initImage: initImage.imageBase64,
          maskPrompt: maskImage.imageBase64 ? undefined : maskPrompt,
          maskImage: maskImage.imageBase64,
        };
      } else if (generationMode === AMAZON_ADVANCED_GENERATION_MODE.IMAGE_CONDITIONING) {
        params = {
          ...params,
          initImage: initImage.imageBase64,
          controlStrength,
          controlMode,
        };
      } else if (generationMode === AMAZON_ADVANCED_GENERATION_MODE.COLOR_GUIDED_GENERATION) {
        params = {
          ...params,
          initImage: initImage.imageBase64,
          colors: colors.split(',').map((color) => color.trim()),
        };
      } else if (generationMode === AMAZON_ADVANCED_GENERATION_MODE.BACKGROUND_REMOVAL) {
        params = {
          ...params,
          initImage: initImage.imageBase64,
        };
      }

      // 解像度の設定
      if (modelConfig.resolutionPresets[0].value.includes(':')) {
        params = {
          ...params,
          aspectRatio: resolution.value,
        };
      }

      return generateImage(
        params,
        imageGenModels.find((m) => m.modelId === imageGenModelId),
      )
        .then((res) => {
          setImage(idx, res);
        })
        .catch((e: ApiError) => {
          const data = e.data as { message?: string; code?: string } | undefined;
          if (data?.code === 'local_sd_unavailable') {
            setImageError(idx, formatLocalSdUnavailableMessage(imageGenModelIds));
            return;
          }
          setImageError(idx, data?.message ?? e.message);
        });
    });

    await Promise.all(promises).finally(() => {
      setGenerating(false);
    });
  };

  const onClickRandomSeed = (selectedImageIndex: number) => {
    setSeed(generateRandomSeed(), selectedImageIndex);
  };

  return {
    handleGenerateImage,
    onClickRandomSeed,
  };
};
