import { AmazonUIImageGenerationMode, ControlMode } from 'genai-web';
import type { KeyboardEvent } from 'react';
import { MdDeleteOutline } from 'react-icons/md';
import { PiDiceFive } from 'react-icons/pi';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { ButtonIcon } from '@/components/ui/ButtonIcon';
import { CustomSelect } from '@/components/ui/CustomSelect';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Divider } from '@/components/ui/dads/Divider';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Ul } from '@/components/ui/dads/Ul';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { Base64Image } from '@/features/generate-image/components/Base64Image';
import { RangeSlider } from '@/features/generate-image/components/RangeSlider';
import {
  type GenerateImageStore,
  useGenerateImageStore,
} from '@/features/generate-image/stores/useGenerateImageStore';
import { findModelDisplayNameByModelId, MODELS } from '@/models';
import { isSubmitKey, submitKeyHint } from '@/utils/keyboard';
import {
  AMAZON_ADVANCED_GENERATION_MODE,
  AMAZON_MODELS,
  COLORS_OPTIONS,
  CONTROL_MODE_OPTIONS,
  GENERATION_MODES,
  STYLE_PRESET_OPTIONS,
} from '../constants';
import { getModeOptions } from '../utils/getModeOptions';

type Props = {
  generating: boolean;
  loadingChat: boolean;
  selectedImageIndex: number;
  setIsOpenSketch: (value: boolean) => void;
  setIsOpenMask: (value: boolean) => void;
  setSelectedImageIndex: (index: number) => void;
  generateImage: (prompt: string, negativePrompt: string) => void;
  clearAll: () => void;
  onClickRandomSeed: () => void;
};

export const ImageGeneratorForm = (props: Props) => {
  const {
    generating,
    loadingChat,
    selectedImageIndex,
    setIsOpenSketch,
    setIsOpenMask,
    setSelectedImageIndex,
    generateImage,
    clearAll,
    onClickRandomSeed,
  } = props;

  const {
    image,
    prompt,
    setPrompt,
    negativePrompt,
    setNegativePrompt,
    generationMode,
    setGenerationMode,
    initImage,
    setInitImage,
    imageGenModelId,
    setImageGenModelId,
    maskImage,
    maskPrompt,
    setMaskPrompt,
    controlStrength,
    setControlStrength,
    cfgScale,
    setCfgScale,
    step,
    setStep,
    stylePreset,
    setStylePreset,
    colors,
    setColors,
    controlMode,
    setControlMode,
    imageStrength,
    setImageStrength,
    imageSample,
    setImageSample,
    seed,
    setSeed,
    resolution,
    setResolution,
    resolutionPresets,
  } = useGenerateImageStore();

  const SEED_MIN = 0;
  const SEED_MAX = 4294967295;
  const parseSeed = (value: string): number | undefined => {
    const parsed = Number.parseFloat(value);
    if (!Number.isFinite(parsed)) return undefined;
    return Math.round(Math.max(SEED_MIN, Math.min(SEED_MAX, parsed)));
  };

  const colorList = colors ? colors.split(',').map((color) => color.trim()) : [];

  const { imageGenModelIds } = MODELS;

  const maskMode =
    generationMode === GENERATION_MODES.INPAINTING ||
    generationMode === GENERATION_MODES.OUTPAINTING;

  const maskPromptSupported =
    imageGenModelId === AMAZON_MODELS.TITAN_V1 ||
    imageGenModelId === AMAZON_MODELS.TITAN_V2 ||
    imageGenModelId === AMAZON_MODELS.NOVA_CANVAS;

  const modeOptions = getModeOptions(imageGenModelId);

  const isImageVariationSupported = modeOptions
    .map((option) => option.value)
    .includes(GENERATION_MODES.IMAGE_VARIATION);

  const isGenerateDisabled =
    (generationMode !== AMAZON_ADVANCED_GENERATION_MODE.BACKGROUND_REMOVAL &&
      (prompt.length === 0 || negativePrompt.length === 0)) ||
    (generationMode !== GENERATION_MODES.TEXT_IMAGE &&
      generationMode !== AMAZON_ADVANCED_GENERATION_MODE.COLOR_GUIDED_GENERATION &&
      !initImage.imageBase64) ||
    ((generationMode === GENERATION_MODES.INPAINTING ||
      generationMode === GENERATION_MODES.OUTPAINTING) &&
      !maskImage.imageBase64 &&
      !maskPrompt) ||
    (generationMode === AMAZON_ADVANCED_GENERATION_MODE.COLOR_GUIDED_GENERATION && !colors);

  const runGenerate = () => {
    if (generating || loadingChat || isGenerateDisabled) {
      return;
    }
    setSelectedImageIndex(0);
    generateImage(prompt, negativePrompt);
  };

  const handleGenerateKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!isSubmitKey(e)) {
      return;
    }
    e.preventDefault();
    runGenerate();
  };

  const generateImageVariant = () => {
    if (image[selectedImageIndex].base64) {
      if (generationMode === GENERATION_MODES.TEXT_IMAGE) {
        setGenerationMode(GENERATION_MODES.IMAGE_VARIATION);
      }
      const img = `data:image/png;base64,${image[selectedImageIndex].base64}`;
      setInitImage({
        imageBase64: img,
        foregroundBase64: img,
        backgroundColor: '',
      });
    }
  };

  return (
    <>
      {generationMode !== 'BACKGROUND_REMOVAL' && (
        <div className='flex flex-col gap-3'>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='generate-image-prompt-input' size='sm'>
              プロンプト
              <RequirementBadge>※必須</RequirementBadge>
            </Label>
            <SupportText className='text-dns-14N-130!' id='generate-image-prompt-input-support'>
              生成したい画像の説明を記載してください。文章ではなく、単語の羅列で記載します。
            </SupportText>
            <AutoResizeTextarea
              id='generate-image-prompt-input'
              value={prompt}
              className='py-1.5!'
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleGenerateKeyDown}
              maxHeight={80}
              rows={2}
              required
              aria-describedby='generate-image-prompt-input-support generate-image-submit-hint'
            />
          </div>

          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='generate-image-negative-prompt-input' size='sm'>
              ネガティブプロンプト
              <RequirementBadge>※必須</RequirementBadge>
            </Label>
            <SupportText
              className='text-dns-14N-130!'
              id='generate-image-negative-prompt-input-support'
            >
              生成したくない要素、排除したい要素を記載してください。文章ではなく、単語の羅列で記載します。
            </SupportText>
            <AutoResizeTextarea
              id='generate-image-negative-prompt-input'
              value={negativePrompt}
              className='py-1.5!'
              onChange={(e) => setNegativePrompt(e.target.value)}
              onKeyDown={handleGenerateKeyDown}
              maxHeight={80}
              rows={2}
              required
              aria-describedby='generate-image-negative-prompt-input-support generate-image-submit-hint'
            />
          </div>
        </div>
      )}

      <div className='mt-2 mb-2 grid grid-cols-1 gap-2'>
        <CustomSelect
          label='モデル'
          labelClassName='text-std-16B-170 mt-0!'
          isVertical
          isFullWidth
          value={imageGenModelId}
          onChange={setImageGenModelId}
          options={imageGenModelIds.map((m) => {
            return { value: m, label: findModelDisplayNameByModelId(m) };
          })}
        />
        {generationMode !== 'BACKGROUND_REMOVAL' && (
          <CustomSelect
            label='サイズ'
            labelClassName='text-std-16B-170 mt-0!'
            isVertical
            isFullWidth
            value={resolution.value}
            onChange={(value: string) => {
              const selectedResolution = resolutionPresets.find(
                (option: GenerateImageStore['resolution']) => option.value === value,
              );
              if (selectedResolution) {
                setResolution(selectedResolution);
              }
            }}
            options={resolutionPresets}
          />
        )}
      </div>

      {generationMode !== 'BACKGROUND_REMOVAL' && (
        <div className='mb-6 grid w-full grid-cols-1 gap-4'>
          <div className='relative col-span-2 flex flex-col items-start lg:col-span-1'>
            <div className='w-full'>
              <div className='flex flex-col items-start gap-1'>
                <div className='flex items-center'>
                  <Label size='sm' id='generate-image-seed-label' htmlFor='generate-image-seed'>
                    シード値
                  </Label>
                </div>
                <SupportText className='text-dns-14N-130!' id='generate-image-seed-support'>
                  乱数のシード値です。同じシード値を指定すると同じ画像が生成されます。
                </SupportText>
                <LoadingButton size='xs' variant='outline' onClick={onClickRandomSeed}>
                  <PiDiceFive className='mr-1 text-lg' />
                  ランダムなシード値を指定
                </LoadingButton>
                <Input
                  blockSize='sm'
                  className='my-1 self-start'
                  type='number'
                  id='generate-image-seed'
                  aria-describedby='generate-image-seed-support'
                  min={SEED_MIN}
                  max={SEED_MAX}
                  step={1}
                  value={seed[selectedImageIndex]}
                  onChange={(e) => {
                    const value = parseSeed(e.target.value);
                    if (value !== undefined) {
                      setSeed(value, selectedImageIndex);
                    }
                  }}
                />
              </div>
              <div className='mt-2 flex'>
                <input
                  type='range'
                  aria-labelledby='generate-image-seed-label'
                  aria-describedby='generate-image-seed-support'
                  className='mb-6 h-1 w-full cursor-pointer'
                  value={seed[selectedImageIndex]}
                  min={SEED_MIN}
                  max={SEED_MAX}
                  step={1}
                  onChange={(e) => {
                    const value = parseSeed(e.target.value);
                    if (value !== undefined) {
                      setSeed(value, selectedImageIndex);
                    }
                  }}
                />
              </div>
            </div>
          </div>

          <RangeSlider
            className='col-span-2 lg:col-span-1'
            label='画像生成数'
            id='generate-image-number'
            min={1}
            max={7}
            value={imageSample}
            onChange={setImageSample}
            help='シード値をランダム設定しながら画像を指定の数だけ同時に生成します。（最大7枚まで）'
            helpTextClass='!text-dns-14N-130'
          />
        </div>
      )}

      <Divider className='my-4' />

      <div className='flex flex-col gap-3'>
        <h4 className='mb-2 text-std-17B-170'>パラメーター設定</h4>
        <div>
          <CustomSelect
            label='GenerationMode'
            labelClassName='text-std-16B-170'
            isVertical
            isFullWidth
            options={modeOptions}
            value={generationMode}
            onChange={(v) => setGenerationMode(v as AmazonUIImageGenerationMode)}
          />
          <Disclosure className='mt-2'>
            <DisclosureSummary>GenerationModeの各項目について</DisclosureSummary>
            <Ul className='mt-2 ml-4'>
              <li>TEXT_IMAGE: テキストから画像を生成します</li>
              <li>IMAGE_VARIATION: 参照画像から類似画像を生成します</li>
              <li>INPAINTING: 画像の一部を編集します</li>
              <li>OUTPAINTING: 画像を拡張します</li>
              <li>IMAGE_CONDITIONING: 構図を反映します</li>
              <li>COLOR_GUIDED_GENERATION: 配色指定で生成します</li>
              <li>BACKGROUND_REMOVAL: 背景を除去します</li>
            </Ul>
          </Disclosure>
        </div>

        {generationMode !== GENERATION_MODES.TEXT_IMAGE && (
          <div className='mt-3 mb-2'>
            <div className='flex flex-col gap-1.5'>
              <p className='text-std-16B-170'>初期画像</p>
              <SupportText className='text-dns-14N-130!'>
                画像生成の初期状態となる画像を設定できます。初期画像を設定することで、初期画像に近い画像を生成するように誘導できます。
              </SupportText>
              <Base64Image
                alt='初期画像'
                className='my-3 size-32 self-center'
                imageBase64={initImage.imageBase64}
                format={'image/png'}
              />
              <div className='flex flex-col gap-2'>
                {generationMode === GENERATION_MODES.IMAGE_VARIATION &&
                  image[selectedImageIndex].base64 &&
                  isImageVariationSupported && (
                    <LoadingButton variant='outline' size='sm' onClick={generateImageVariant}>
                      選択中の画像を初期画像に設定する
                    </LoadingButton>
                  )}

                <LoadingButton
                  variant='outline'
                  size='sm'
                  onClick={() => {
                    setIsOpenSketch(true);
                  }}
                >
                  初期画像の設定
                </LoadingButton>
              </div>
            </div>
          </div>
        )}

        {maskMode && (
          <div className='mt-3 mb-2'>
            <div className='flex flex-col gap-1.5'>
              <p className='text-std-16B-170'>マスク画像</p>
              <SupportText className='text-dns-14N-130!'>
                画像のマスクを設定できます。マスク画像を設定することで、マスクされた領域（Inpaint）もしくは外側の領域（Outpaint）を生成できます。マスクプロンプトと併用はできません。
              </SupportText>
              <Base64Image
                alt='マスク画像'
                className='my-3 size-32 self-center'
                imageBase64={maskImage.imageBase64}
                format={'image/png'}
              />
              <LoadingButton
                variant='outline'
                size='sm'
                disabled={!!maskPrompt}
                onClick={() => {
                  setIsOpenMask(true);
                }}
              >
                マスク画像の設定
              </LoadingButton>
            </div>
          </div>
        )}

        {maskMode && maskPromptSupported && (
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='mask-prompt-input' size='sm'>
              マスクプロンプト
            </Label>
            <SupportText className='text-dns-14N-130!' id='mask-prompt-input-support'>
              マスクしたい/排除したい要素（Inpaint）、マスクしたくない/残したい要素（Outpaint）を記載してください。文章ではなく、単語の羅列で記載します。マスク画像と併用はできません。
            </SupportText>
            <AutoResizeTextarea
              id='mask-prompt-input'
              value={maskPrompt}
              onChange={(e) => setMaskPrompt(e.target.value)}
              onKeyDown={handleGenerateKeyDown}
              maxHeight={80}
              rows={2}
              className='w-full'
              aria-disabled={!!maskImage.imageBase64}
              aria-describedby='mask-prompt-input-support generate-image-submit-hint'
            />
          </div>
        )}
        {generationMode === 'COLOR_GUIDED_GENERATION' && (
          <div className='space-y-4'>
            <div>
              <CustomSelect
                label='プリセットパレット'
                labelClassName='text-std-16B-170'
                isVertical
                options={COLORS_OPTIONS}
                value={COLORS_OPTIONS.find((option) => option.value === colors)?.value || ''}
                onChange={(value) => {
                  setColors(value);
                }}
                isFullWidth
              />
            </div>

            <fieldset>
              <legend className='text-std-16B-170'>カスタムカラー</legend>
              <SupportText className='mt-2 text-dns-14N-130!'>
                カスタムカラーは5色まで設定できます
              </SupportText>
              <div className='mt-2 space-y-2'>
                {colorList.map((color, index) => (
                  <div key={index} className='flex items-center gap-2'>
                    <input
                      aria-label={`カスタムカラー${index + 1}`}
                      type='color'
                      value={color}
                      id={`custom-color-${index + 1}`}
                      onChange={(e) => {
                        const newColors = [...colorList];
                        newColors[index] = e.target.value;
                        setColors(newColors.join(','));
                      }}
                      className='h-8 w-8 bg-white'
                    />
                    <Input
                      aria-label={`カスタムカラー${index + 1}`}
                      value={color}
                      id={`custom-color-code-${index + 1}`}
                      onChange={(e) => {
                        const newColors = [...colorList];
                        newColors[index] = e.target.value;
                        setColors(newColors.join(','));
                      }}
                      className='w-24'
                      blockSize='sm'
                    />
                    <ButtonIcon
                      onClick={() => {
                        const newColors = colorList.filter((_, i) => i !== index);
                        setColors(newColors.join(','));
                      }}
                    >
                      <MdDeleteOutline role='img' aria-label='削除' />
                    </ButtonIcon>
                  </div>
                ))}

                <LoadingButton
                  variant='text'
                  size='sm'
                  onClick={() => {
                    const newColors = [...colorList, '#000000'];
                    setColors(newColors.join(','));
                  }}
                  className='mt-2'
                  disabled={colorList.length >= 5}
                >
                  カラーを追加
                </LoadingButton>
              </div>
            </fieldset>
          </div>
        )}
        {generationMode === 'IMAGE_CONDITIONING' && (
          <div className='mb-2'>
            <CustomSelect
              label='コントロールモード'
              labelClassName='text-std-16B-170'
              isVertical
              options={CONTROL_MODE_OPTIONS}
              value={controlMode}
              onChange={(v) => setControlMode(v as ControlMode)}
              isFullWidth
            />
            <Disclosure className='mt-2'>
              <DisclosureSummary>コントロールモードの各項目について</DisclosureSummary>
              <Ul className='mt-2 ml-4'>
                <li>
                  CANNY_EDGE: 参照画像のエッジを抽出します。詳細な模様などを反映したい場合に最適です
                </li>
                <li>
                  SEGMENTATION:参照画像内を領域に区切ります。複数の物体の位置関係を反映したい場合に最適です
                </li>
              </Ul>
            </Disclosure>
          </div>
        )}
        {generationMode !== 'BACKGROUND_REMOVAL' && (
          <div className='flex flex-col justify-start'>
            <div className='mb-2'>
              <CustomSelect
                label='スタイルプリセット'
                labelClassName='text-std-16B-170'
                className='mb-2'
                isVertical
                isFullWidth
                options={STYLE_PRESET_OPTIONS}
                value={stylePreset}
                onChange={setStylePreset}
              />
            </div>
            <div className='grid grid-cols-1 gap-2'>
              <RangeSlider
                className='w-full'
                label='CFG Scale'
                id='cfg-scale'
                min={0}
                max={30}
                value={cfgScale}
                onChange={setCfgScale}
                help='この値が高いほどプロンプトに対して忠実な画像を生成します。（最大30まで）'
                helpTextClass='!text-dns-14N-130'
              />

              <RangeSlider
                className='w-full'
                label='Step'
                id='step-number'
                min={10}
                max={50}
                value={step}
                onChange={setStep}
                help='画像生成の反復回数です。Step 数が多いほど画像が洗練されますが、生成に時間がかかります。（最大50まで）'
                helpTextClass='!text-dns-14N-130'
              />

              {generationMode === GENERATION_MODES.IMAGE_VARIATION && (
                <RangeSlider
                  className='w-full'
                  label='ImageStrength'
                  id='image-strength'
                  min={0}
                  max={1}
                  step={0.01}
                  value={imageStrength}
                  onChange={setImageStrength}
                  help='1に近いほど「初期画像」に近い画像が生成され、0に近いほど「初期画像」とは異なる画像が生成されます。（最大1まで）'
                  helpTextClass='!text-dns-14N-130'
                />
              )}
              {generationMode === 'IMAGE_CONDITIONING' && (
                <RangeSlider
                  className='w-full'
                  label='ControlStrength'
                  id='control-strength'
                  min={0}
                  max={1}
                  step={0.01}
                  value={controlStrength}
                  onChange={setControlStrength}
                  help='1に近いほど「参照画像」の構図に基づいた画像が生成され、0に近いほど「参照画像」の構図とは異なる画像が生成されます。（最大1まで）'
                  helpTextClass='!text-dns-14N-130'
                />
              )}
            </div>
          </div>
        )}
      </div>

      <SupportText id='generate-image-submit-hint' className='mt-4 mb-2 text-center text-dns-14N-130!'>
        {submitKeyHint}
      </SupportText>

      <div className='flex flex-row-reverse items-center justify-center gap-x-5'>
        <LoadingButton
          variant='solid-fill'
          size='lg'
          onClick={runGenerate}
          loading={generating || loadingChat}
          disabled={isGenerateDisabled}
        >
          実行
        </LoadingButton>

        <LoadingButton
          variant='text'
          size='lg'
          onClick={() => {
            clearAll();
          }}
          disabled={generating || loadingChat}
        >
          クリア
        </LoadingButton>
      </div>
    </>
  );
};
