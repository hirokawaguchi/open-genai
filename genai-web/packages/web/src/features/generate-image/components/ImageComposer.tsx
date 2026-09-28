import type { KeyboardEvent } from 'react';
import { useRef } from 'react';
import { CustomSelect } from '@/components/ui/CustomSelect';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useSelectedModel } from '@/hooks/useSelectedModel';
import { findModelDisplayNameByModelId, MODELS } from '@/models';
import { STYLE_PRESET_OPTIONS } from '../constants';
import { RangeSlider } from './RangeSlider';
import { useGenerateImageStore } from '../stores/useGenerateImageStore';

const LOCAL_SD = 'local-sd';

type Props = {
  draft: string;
  attachmentUrl: string;
  continuing?: boolean;
  busy: boolean;
  refining: boolean;
  refineError?: string;
  onChangeDraft: (value: string) => void;
  onAttach: (dataUrl: string) => void;
  onClearAttachment: () => void;
  onRefine: () => void;
  onSend: () => void;
};

export const ImageComposer = ({
  draft,
  attachmentUrl,
  continuing = false,
  busy,
  refining,
  refineError,
  onChangeDraft,
  onAttach,
  onClearAttachment,
  onRefine,
  onSend,
}: Props) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const { selectedModelId, setSelectedModelId } = useSelectedModel();
  const { modelIds, imageGenModelIds } = MODELS;
  const {
    imageGenModelId,
    setImageGenModelId,
    resolution,
    setResolution,
    resolutionPresets,
    stylePreset,
    setStylePreset,
    step,
    setStep,
    cfgScale,
    setCfgScale,
    imageStrength,
    setImageStrength,
  } = useGenerateImageStore();

  const localSd = imageGenModelId === LOCAL_SD;

  const onPickFile = (file: File | undefined) => {
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      onAttach(String(reader.result || ''));
      setStylePreset('');
    };
    reader.readAsDataURL(file);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (!busy && draft.trim()) {
        onSend();
      }
    }
  };

  return (
    <div className='border-t border-solid-gray-300 bg-white pt-2'>
      <Disclosure>
        <DisclosureSummary>設定</DisclosureSummary>
        <div className='grid gap-3 py-3'>
          <CustomSelect
            label='サイズ'
            isVertical
            isFullWidth
            value={resolution.value}
            onChange={(value: string) => {
              const next = resolutionPresets.find((item) => item.value === value);
              if (next) {
                setResolution(next);
              }
            }}
            options={resolutionPresets}
          />
          <CustomSelect
            label='雰囲気'
            isVertical
            isFullWidth
            value={stylePreset}
            onChange={setStylePreset}
            options={STYLE_PRESET_OPTIONS}
          />
          {localSd && (
            <>
              <RangeSlider
                label='CFG Scale'
                id='image-cfg'
                min={1}
                max={20}
                value={cfgScale}
                onChange={setCfgScale}
                help='プロンプトへの忠実さです。'
              />
              <RangeSlider
                label='Step'
                id='image-step'
                min={1}
                max={50}
                value={step}
                onChange={setStep}
                help='描き込みの回数です。増やすと時間がかかります。'
              />
            </>
          )}
          {localSd && attachmentUrl && (
            <RangeSlider
              label='変更の強さ'
              id='image-strength'
              min={0}
              max={1}
              step={0.01}
              value={imageStrength}
              onChange={setImageStrength}
              help='上げると新しい絵に近づき、下げると元画像に近づきます。'
            />
          )}
        </div>
      </Disclosure>

      <div className='mt-2 grid gap-2 sm:grid-cols-2'>
        <CustomSelect
          label='プロンプト'
          isVertical
          isFullWidth
          value={selectedModelId}
          onChange={setSelectedModelId}
          options={modelIds.map((modelId) => ({
            value: modelId,
            label: findModelDisplayNameByModelId(modelId),
          }))}
        />
        <CustomSelect
          label='画像'
          isVertical
          isFullWidth
          value={imageGenModelId}
          onChange={setImageGenModelId}
          options={imageGenModelIds.map((modelId) => ({
            value: modelId,
            label: findModelDisplayNameByModelId(modelId),
          }))}
        />
      </div>

      {attachmentUrl && (
        <div className='mt-2 flex items-center gap-2'>
          <img src={attachmentUrl} alt='添付画像' className='h-16 w-16 rounded-8 object-cover' />
          <Button type='button' variant='outline' size='sm' onClick={onClearAttachment}>
            添付を外す
          </Button>
        </div>
      )}

      <div className='mt-2 flex items-end gap-2'>
        <input
          ref={fileRef}
          type='file'
          accept='image/*'
          className='hidden'
          onChange={(event) => {
            onPickFile(event.target.files?.[0]);
            event.target.value = '';
          }}
        />
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={() => fileRef.current?.click()}
          disabled={busy}
        >
          画像を添付
        </Button>
        <AutoResizeTextarea
          id='image-chat-input'
          value={draft}
          onChange={(event) => onChangeDraft(event.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxHeight={120}
          className='min-w-0 flex-1'
          placeholder={
            attachmentUrl || continuing
              ? '前の画像をどう変えるかを書いてください'
              : '作りたい画像を書いてください'
          }
          disabled={busy}
        />
      </div>
      <div className='mt-2 flex justify-end gap-2 pb-2'>
        <LoadingButton
          type='button'
          variant='outline'
          size='sm'
          loading={refining}
          disabled={busy || !draft.trim()}
          onClick={onRefine}
        >
          プロンプトを整える
        </LoadingButton>
        <LoadingButton
          type='button'
          variant='solid-fill'
          size='sm'
          loading={busy && !refining}
          disabled={busy || !draft.trim()}
          onClick={onSend}
        >
          送信
        </LoadingButton>
      </div>
      {refineError && (
        <p className='pb-2 text-std-16N-170 text-error-1' role='alert'>
          {refineError}
        </p>
      )}
    </div>
  );
};
