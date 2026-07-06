import { AmazonBaseImageGenerationMode, AmazonUIImageGenerationMode, ControlMode } from 'genai-web';

export const MAX_SAMPLE = 7;

export const AMAZON_MODELS = {
  TITAN_V1: 'amazon.titan-image-generator-v1',
  TITAN_V2: 'amazon.titan-image-generator-v2:0',
  NOVA_CANVAS: 'amazon.nova-canvas-v1:0',
};

const LOCAL_SD_MODEL = 'local-sd';

const STABILITY_AI_MODELS = {
  STABLE_DIFFUSION_XL: 'stability.stable-diffusion-xl-v1',
  SD3_LARGE: 'stability.sd3-large-v1:0',
  STABLE_IMAGE_CORE1_0: 'stability.stable-image-core-v1:0',
  STABLE_IMAGE_CORE1_1: 'stability.stable-image-core-v1:1',
  STABLE_IMAGE_ULTRA1_0: 'stability.stable-image-ultra-v1:0',
  STABLE_IMAGE_ULTRA1_1: 'stability.stable-image-ultra-v1:1',
  SD3_5: 'stability.sd3-5-large-v1:0',
};

export const GENERATION_MODES: Record<
  AmazonBaseImageGenerationMode,
  AmazonBaseImageGenerationMode
> = {
  TEXT_IMAGE: 'TEXT_IMAGE',
  IMAGE_VARIATION: 'IMAGE_VARIATION',
  INPAINTING: 'INPAINTING',
  OUTPAINTING: 'OUTPAINTING',
} as const;

export const AMAZON_ADVANCED_GENERATION_MODE: Record<
  AmazonUIImageGenerationMode,
  AmazonUIImageGenerationMode
> = {
  ...GENERATION_MODES,
  IMAGE_CONDITIONING: 'IMAGE_CONDITIONING',
  COLOR_GUIDED_GENERATION: 'COLOR_GUIDED_GENERATION',
  BACKGROUND_REMOVAL: 'BACKGROUND_REMOVAL',
};

// Titan Image Generator v2のImage Conditioning適用時のControl Mode
// https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-image.html
export const CONTROL_MODE_OPTIONS = ['CANNY_EDGE', 'SEGMENTATION'].map((s) => ({
  value: s as ControlMode,
  label: s as ControlMode,
}));

// StableDiffusion の StylePreset
// 一覧は、以下の style_preset を参照
// https://platform.stability.ai/docs/api-reference#tag/v1generation/operation/textToImage
export const STYLE_PRESET_OPTIONS = [
  {
    value: '',
    label: '未設定',
  },
  {
    value: '3d-model',
    label: '3d-model',
  },
  {
    value: 'analog-film',
    label: 'analog-film',
  },
  {
    value: 'anime',
    label: 'anime',
  },
  {
    value: 'cinematic',
    label: 'cinematic',
  },
  {
    value: 'comic-book',
    label: 'comic-book',
  },
  {
    value: 'digital-art',
    label: 'digital-art',
  },
  {
    value: 'enhance',
    label: 'enhance',
  },
  {
    value: 'fantasy-art',
    label: 'fantasy-art',
  },
  {
    value: 'isometric',
    label: 'isometric',
  },
  {
    value: 'line-art',
    label: 'line-art',
  },
  {
    value: 'low-poly',
    label: 'low-poly',
  },
  {
    value: 'modeling-compound',
    label: 'modeling-compound',
  },
  {
    value: 'neon-punk',
    label: 'neon-punk',
  },
  {
    value: 'origami',
    label: 'origami',
  },
  {
    value: 'photographic',
    label: 'photographic',
  },
  {
    value: 'pixel-art',
    label: 'pixel-art',
  },
  {
    value: 'tile-texture',
    label: 'tile-texture',
  },
].map((s) => ({
  value: s.value,
  label: s.label,
}));

export const COLORS_OPTIONS = [
  {
    value: '#efd9b4,#d6a692,#a39081,#4d6164,#292522',
    label: 'Earthy Neutrals',
  },
  {
    value: '#001449,#012677,#005bc5,#00b4fc,#17f9ff',
    label: 'Ocean Blues',
  },
  {
    value: '#c7003f,#f90050,#f96a00,#faab00,#daf204',
    label: 'Fiery Sunset',
  },
  {
    value: '#ffd100,#ffee32,#ffd100,#00a86b,#004b23',
    label: 'Lemon Lime',
  },
  {
    value: '#006400,#228B22,#32CD32,#90EE90,#98FB98',
    label: 'Forest Greens',
  },
  {
    value: '#4B0082,#8A2BE2,#9370DB,#BA55D3,#DDA0DD',
    label: 'Royal Purples',
  },
  {
    value: '#FF8C00,#FFA500,#FFD700,#FFFF00,#F0E68C',
    label: 'Golden Ambers',
  },
  {
    value: '#FFB6C1,#FFC0CB,#FFE4E1,#E6E6FA,#F0F8FF',
    label: 'Soft Pastels',
  },
  {
    value: '#FF00FF,#00FFFF,#FF0000,#00FF00,#0000FF',
    label: 'Vivid Rainbow',
  },
  {
    value: '#000000,#333333,#666666,#999999,#CCCCCC',
    label: 'Classic Monochrome',
  },
  {
    value: '#FFFFFF,#F2F2F2,#E6E6E6,#D9D9D9,#CCCCCC',
    label: 'Light Grayscale',
  },
  {
    value: '#704214,#8B4513,#A0522D,#CD853F,#DEB887',
    label: 'Vintage Sepia',
  },
  {
    value: '#FF9900,#232F3E,#ffffff,#00464F,#6C7778',
    label: 'Smile and Sky',
  },
];

type ModelInfo<T extends 'base' | 'advanced'> = {
  supportedModes: T extends 'base'
    ? AmazonBaseImageGenerationMode[]
    : AmazonUIImageGenerationMode[];
  resolutionPresets: { value: string; label: string }[];
};

const DEFAULT_MODEL_PRESETS = [
  { value: '512 x 512', label: '512 x 512' },
  { value: '1024 x 1024', label: '1024 x 1024' },
  { value: '1280 x 768', label: '1280 x 768' },
  { value: '768 x 1280', label: '768 x 1280' },
];

export const STABILITY_AI_2024_MODEL_PRESETS = [
  { value: '1:1', label: '1024 x 1024' },
  { value: '5:4', label: '1088 x 896' },
  { value: '3:2', label: '1216 x 832' },
  { value: '16:9', label: '1344 x 768' },
  { value: '21:9', label: '1536 x 640' },
];

export const MODEL_INFO: Record<string, ModelInfo<'base' | 'advanced'>> = {
  [LOCAL_SD_MODEL]: {
    supportedModes: [
      GENERATION_MODES.TEXT_IMAGE,
      GENERATION_MODES.IMAGE_VARIATION,
    ],
    resolutionPresets: DEFAULT_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.STABLE_DIFFUSION_XL]: {
    supportedModes: [
      GENERATION_MODES.TEXT_IMAGE,
      GENERATION_MODES.IMAGE_VARIATION,
      GENERATION_MODES.INPAINTING,
      GENERATION_MODES.OUTPAINTING,
    ],
    resolutionPresets: DEFAULT_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.SD3_LARGE]: {
    supportedModes: [GENERATION_MODES.TEXT_IMAGE, GENERATION_MODES.IMAGE_VARIATION],
    resolutionPresets: STABILITY_AI_2024_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.STABLE_IMAGE_CORE1_0]: {
    supportedModes: [GENERATION_MODES.TEXT_IMAGE],
    resolutionPresets: STABILITY_AI_2024_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.STABLE_IMAGE_CORE1_1]: {
    supportedModes: [GENERATION_MODES.TEXT_IMAGE],
    resolutionPresets: STABILITY_AI_2024_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.STABLE_IMAGE_ULTRA1_0]: {
    supportedModes: [GENERATION_MODES.TEXT_IMAGE],
    resolutionPresets: STABILITY_AI_2024_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.STABLE_IMAGE_ULTRA1_1]: {
    supportedModes: [GENERATION_MODES.TEXT_IMAGE],
    resolutionPresets: STABILITY_AI_2024_MODEL_PRESETS,
  },
  [STABILITY_AI_MODELS.SD3_5]: {
    supportedModes: [GENERATION_MODES.TEXT_IMAGE, GENERATION_MODES.IMAGE_VARIATION],
    resolutionPresets: STABILITY_AI_2024_MODEL_PRESETS,
  },
  [AMAZON_MODELS.TITAN_V1]: {
    supportedModes: [
      GENERATION_MODES.TEXT_IMAGE,
      GENERATION_MODES.IMAGE_VARIATION,
      GENERATION_MODES.INPAINTING,
      GENERATION_MODES.OUTPAINTING,
    ],
    resolutionPresets: DEFAULT_MODEL_PRESETS,
  },
  [AMAZON_MODELS.TITAN_V2]: {
    supportedModes: [
      AMAZON_ADVANCED_GENERATION_MODE.TEXT_IMAGE,
      AMAZON_ADVANCED_GENERATION_MODE.IMAGE_VARIATION,
      AMAZON_ADVANCED_GENERATION_MODE.INPAINTING,
      AMAZON_ADVANCED_GENERATION_MODE.OUTPAINTING,
      AMAZON_ADVANCED_GENERATION_MODE.IMAGE_CONDITIONING,
      AMAZON_ADVANCED_GENERATION_MODE.COLOR_GUIDED_GENERATION,
      AMAZON_ADVANCED_GENERATION_MODE.BACKGROUND_REMOVAL,
    ],
    resolutionPresets: DEFAULT_MODEL_PRESETS,
  },
  [AMAZON_MODELS.NOVA_CANVAS]: {
    supportedModes: [
      AMAZON_ADVANCED_GENERATION_MODE.TEXT_IMAGE,
      AMAZON_ADVANCED_GENERATION_MODE.IMAGE_VARIATION,
      AMAZON_ADVANCED_GENERATION_MODE.INPAINTING,
      AMAZON_ADVANCED_GENERATION_MODE.OUTPAINTING,
      AMAZON_ADVANCED_GENERATION_MODE.IMAGE_CONDITIONING,
      AMAZON_ADVANCED_GENERATION_MODE.COLOR_GUIDED_GENERATION,
      AMAZON_ADVANCED_GENERATION_MODE.BACKGROUND_REMOVAL,
    ],
    resolutionPresets: DEFAULT_MODEL_PRESETS,
  },
};
