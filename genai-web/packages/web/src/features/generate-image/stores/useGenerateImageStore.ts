import type { AmazonUIImageGenerationMode, ControlMode } from 'genai-web';
import { produce } from 'immer';
import { createWithEqualityFn as create } from 'zustand/traditional';
import {
  AMAZON_ADVANCED_GENERATION_MODE,
  COLORS_OPTIONS,
  MAX_SAMPLE,
  MODEL_INFO,
} from '../constants';
import type { Canvas } from '../types';
import { getResolutionPresets } from '../utils/getResolutionPresets';

type Resolution = {
  value: string;
  label: string;
};

// 画像生成の初期 step / cfgScale はビルド時 env で切り替える。
// 既定は 50 / 7（標準的な A1111/SDXL 向け）。CPU-only の FastSD/LCM を使うビルドでは
// VITE_APP_IMAGE_DEFAULT_STEP=4 / VITE_APP_IMAGE_DEFAULT_CFG=1 を指定する。
const positiveNumberEnv = (value: string | undefined, fallback: number): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};
const DEFAULT_STEP = positiveNumberEnv(import.meta.env.VITE_APP_IMAGE_DEFAULT_STEP, 50);
const DEFAULT_CFG_SCALE = positiveNumberEnv(import.meta.env.VITE_APP_IMAGE_DEFAULT_CFG, 7);

type ImageResult = {
  base64: string;
  error: boolean;
  errorMessage?: string;
};

type GenerateImageState = {
  imageGenModelId: string;
  prompt: string;
  negativePrompt: string;
  resolution: Resolution;
  resolutionPresets: Resolution[];
  stylePreset: string;
  seed: number[];
  step: number;
  cfgScale: number;
  imageStrength: number;
  controlStrength: number;
  controlMode: ControlMode;
  generationMode: AmazonUIImageGenerationMode;
  initImage: Canvas;
  maskImage: Canvas;
  maskPrompt: string;
  colors: string;
  imageSample: number;
  image: ImageResult[];
  chatContent: string;
};

type GenerateImageActions = {
  setImageGenModelId: (imageGenModelId: string) => void;
  setPrompt: (prompt: string) => void;
  setNegativePrompt: (negativePrompt: string) => void;
  setResolution: (resolution: Resolution) => void;
  setStylePreset: (stylePreset: string) => void;
  setSeed: (seed: number, index: number) => void;
  setStep: (step: number) => void;
  setCfgScale: (cfgScale: number) => void;
  setImageStrength: (imageStrength: number) => void;
  setControlStrength: (controlStrength: number) => void;
  setControlMode: (controlMode: ControlMode) => void;
  setGenerationMode: (generationMode: AmazonUIImageGenerationMode) => void;
  setInitImage: (initImage: Canvas) => void;
  setMaskImage: (maskImage: Canvas) => void;
  setMaskPrompt: (maskPrompt: string) => void;
  setColors: (colors: string) => void;
  setImageSample: (imageSample: number) => void;
  setImage: (index: number, base64: string) => void;
  setImageError: (index: number, errorMessage: string) => void;
  clearImage: () => void;
  setChatContent: (chatContent: string) => void;
  clear: () => void;
};

export type GenerateImageStore = GenerateImageState & GenerateImageActions;

const createInitialState = (): GenerateImageState => ({
  imageGenModelId: '',
  prompt: '',
  negativePrompt: '',
  resolution: { value: '', label: '' },
  resolutionPresets: getResolutionPresets(''),
  stylePreset: '',
  seed: [0, ...new Array(MAX_SAMPLE - 1).fill(-1)],
  step: DEFAULT_STEP,
  cfgScale: DEFAULT_CFG_SCALE,
  imageStrength: 0.35,
  controlStrength: 0.7,
  controlMode: 'CANNY_EDGE',
  generationMode: 'TEXT_IMAGE',
  initImage: {
    imageBase64: '',
    foregroundBase64: '',
    backgroundColor: '',
  },
  maskImage: {
    imageBase64: '',
    foregroundBase64: '',
    backgroundColor: '',
  },
  maskPrompt: '',
  colors: COLORS_OPTIONS[0].value,
  imageSample: 3,
  image: new Array(MAX_SAMPLE).fill({
    base64: '',
    error: false,
  }),
  chatContent: '',
});

export const useGenerateImageStore = create<GenerateImageStore>((set, get) => {
  const initialState = createInitialState();

  // BACKGROUND_REMOVAL モードから他のモードに戻す際に復元するための imageSample の値
  let previousImageSample = initialState.imageSample;

  return {
    ...initialState,
    setImageGenModelId: (imageGenModelId) => {
      const newResolutionPresets = getResolutionPresets(imageGenModelId);
      const newResolution = newResolutionPresets[0];
      const currentMode = get().generationMode;
      const availableModes = MODEL_INFO[imageGenModelId]?.supportedModes || [
        AMAZON_ADVANCED_GENERATION_MODE.TEXT_IMAGE,
      ];
      const isValidMode = availableModes.some((mode) => mode === currentMode);
      set({
        imageGenModelId,
        resolutionPresets: newResolutionPresets,
        resolution: newResolution,
        generationMode: isValidMode ? currentMode : availableModes[0],
      });
    },
    setPrompt: (prompt) => set({ prompt }),
    setNegativePrompt: (negativePrompt) => set({ negativePrompt }),
    setResolution: (resolution) => set({ resolution }),
    setStylePreset: (stylePreset) => set({ stylePreset }),
    setSeed: (seed, index) =>
      set({
        seed: produce(get().seed, (draft) => {
          draft[index] = seed;
        }),
      }),
    setStep: (step) => set({ step }),
    setCfgScale: (cfgScale) => set({ cfgScale }),
    setImageStrength: (imageStrength) => set({ imageStrength }),
    setControlStrength: (controlStrength) => set({ controlStrength }),
    setControlMode: (controlMode) => set({ controlMode }),
    setGenerationMode: (generationMode) => {
      const currentMode = get().generationMode;
      if (currentMode === generationMode) {
        set({ generationMode });
        return;
      }
      if (generationMode === 'BACKGROUND_REMOVAL') {
        // BACKGROUND_REMOVAL は 1 枚のみ生成可能なため、現在の値を退避して 1 に固定する
        previousImageSample = get().imageSample;
        set({ generationMode, imageSample: 1 });
      } else if (currentMode === 'BACKGROUND_REMOVAL') {
        // BACKGROUND_REMOVAL から他モードに戻す際は退避していた値に復元する
        set({ generationMode, imageSample: previousImageSample });
      } else {
        set({ generationMode });
      }
    },
    setInitImage: (initImage) => set({ initImage }),
    setMaskImage: (maskImage) => set({ maskImage }),
    setMaskPrompt: (maskPrompt) => set({ maskPrompt }),
    setColors: (colors) => set({ colors }),
    setImageSample: (imageSample) => set({ imageSample }),
    setImage: (index, base64) =>
      set({
        image: produce(get().image, (draft) => {
          draft.splice(index, 1, { base64, error: false });
        }),
      }),
    setImageError: (index, errorMessage) =>
      set({
        image: produce(get().image, (draft) => {
          draft.splice(index, 1, { base64: '', error: true, errorMessage });
        }),
      }),
    clearImage: () => set({ image: [...initialState.image] }),
    setChatContent: (chatContent) => set({ chatContent }),
    clear: () => set(createInitialState()),
  };
});
