import { useState } from 'react';
import { PiBookOpenBold } from 'react-icons/pi';
import { useLocation } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { RightPanelCloseIcon } from '@/components/ui/icons/RightPanelClose';
import { RightPanelOpenIcon } from '@/components/ui/icons/RightPanelOpen';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { APP_TITLE } from '@/constants';
import { useGenerateImageHandler } from '@/features/generate-image/hooks/useGenerateImageHandler';
import { useReset } from '@/features/generate-image/hooks/useReset';
import { useSetDefaultValues } from '@/features/generate-image/hooks/useSetDefaultValues';
import { useGenerateImageStore } from '@/features/generate-image/stores/useGenerateImageStore';
import { useChat } from '@/hooks/useChat';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { useScreen } from '@/hooks/useScreen';
import { MODELS } from '@/models';
import { GeneratedImages } from './components/GeneratedImages';
import { GenerateImageAssistant } from './components/GenerateImageAssistant';
import { GenerateImageInput } from './components/GenerateImageInput';
import { GenerateImageStickyHeader } from './components/GenerateImageStickyHeader';
import { ImageGeneratorForm } from './components/ImageGeneratorForm';
import { SketchMaskDialogs } from './components/SketchMaskDialogs';
import { Canvas } from './types';

export const GenerateImagePage = () => {
  const {
    prompt,
    setPrompt,
    negativePrompt,
    setNegativePrompt,
    resolution,
    stylePreset,
    setStylePreset,
    initImage,
    setInitImage,
    maskImage,
    setMaskImage,
    chatContent,
    setChatContent,
    setImageGenModelId,
    clear,
  } = useGenerateImageStore();

  const { pathname } = useLocation();
  const { loading: loadingChat, postChat, clear: clearChat } = useChat(pathname);
  const { scrollToBottom } = useScreen({ useWindowScroll: true });

  const [generating, setGenerating] = useState(false);
  const [isFormGenerating, setIsFormGenerating] = useState(false);

  const { liveStatusMessage } = useLiveStatusMessage({
    active: true,
    loading: isFormGenerating,
    messages: {
      loading: 'AIが画像を生成しています...',
      loadingContinue: 'AIが引き続き画像を生成しています...',
      completed: '画像の生成が完了しました',
    },
  });
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
  const [isOpenSketch, setIsOpenSketch] = useState(false);
  const [isOpenMask, setIsOpenMask] = useState(false);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);

  const { imageGenModelIds } = MODELS;
  const { handleGenerateImage, onClickRandomSeed } = useGenerateImageHandler(setGenerating);

  const [width, height] = resolution.label.split('x').map((v) => Number(v));

  useReset();

  useSetDefaultValues();

  const onChangeInitImageBase64 = (s: Canvas) => {
    setInitImage(s);
    setIsOpenSketch(false);
  };

  const onChangeMaskImageBase64 = (s: Canvas) => {
    setMaskImage(s);
    setIsOpenMask(false);
  };

  const clearAll = () => {
    setSelectedImageIndex(0);
    clear();
    clearChat();
    if (imageGenModelIds.length > 0) {
      setImageGenModelId(imageGenModelIds[0]);
    }
  };

  const generateImageWithAnnounce = async (prompt: string, negativePrompt: string) => {
    setIsFormGenerating(true);
    try {
      await handleGenerateImage(prompt, negativePrompt);
    } finally {
      setIsFormGenerating(false);
    }
  };

  const onSendChat = () => {
    postChat(chatContent);
    setChatContent('');
    scrollToBottom();
  };

  return (
    <>
      <PageTitle title={`画像を生成${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div className='mx-auto max-w-(--page-width) min-h-[calc(100dvh-var(--header-height))] pt-6 px-6 lg:px-8 lg:pt-8'>
        <div className='mb-3.5'>
          <BreadcrumbsNav
            items={[
              { label: 'ホーム', to: '/' },
              { label: 'AIアプリ', to: '/apps' },
              { label: '画像を生成' },
            ]}
            className='mb-4'
          />
          <h1 className='flex justify-start text-std-20B-160 lg:text-std-24B-150'>画像を生成</h1>
        </div>

        <Disclosure className='mb-6 rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
          <DisclosureSummary>
            <span className='flex items-center text-std-16B-150'>
              <PiBookOpenBold className='mr-2 size-5 flex-none' />
              使い方（クリックで開閉）
            </span>
          </DisclosureSummary>
          <div className='prose prose-sm mt-3 max-w-full'>
            <h2>このアプリでできること</h2>
            <p>
              プロンプト（文章）から画像を生成します。資料の挿絵やイメージ案の作成、
              たたき台づくりに役立ちます。
            </p>
            <h3>操作方法</h3>
            <ol>
              <li>下部の入力欄に、生成したい画像の内容を入力して送信します（英語推奨・具体的に）。</li>
              <li>右側の「生成結果」に画像が表示されます。</li>
              <li>
                「詳細設定」を開くと、ネガティブプロンプト・画像サイズ・ステップ数・シード・
                スタイルなどを調整できます。
              </li>
              <li>スケッチ／マスク機能で、下絵や修正したい範囲を指定した生成もできます。</li>
            </ol>
            <h3>入力例・コツ</h3>
            <ul>
              <li>
                プロンプトは具体的に。例:{' '}
                <code>a flat vector illustration of a city hall, simple, clean</code>
              </li>
              <li>
                避けたい要素はネガティブプロンプトに。例: <code>blurry, text, watermark</code>
              </li>
              <li>ステップ数を増やすと描き込みが増えますが、生成に時間がかかります。</li>
            </ul>
            <Disclosure className='my-4'>
              <DisclosureSummary>仕組み・注意</DisclosureSummary>
              <div className='pl-7'>
                <ul>
                  <li>生成AI（画像生成モデル）がプロンプトに基づいて画像を生成します。</li>
                  <li>同じ入力でも生成結果は毎回変わることがあります（シード固定で再現性を高められます）。</li>
                  <li>生成画像の公開・配布時は、著作権・肖像権にご注意ください。</li>
                </ul>
              </div>
            </Disclosure>
          </div>
        </Disclosure>

        <div className='flex justify-between gap-12 xl:gap-16'>
          <div className='flex min-w-0 flex-1 flex-col'>
            <GenerateImageStickyHeader />

            <div className='flex-1 pt-4 pb-6 px-2'>
              <GenerateImageAssistant
                isGeneratingImage={generating}
                onGenerate={async (p, np, sp) => {
                  if (p !== prompt || np !== negativePrompt || (sp ?? '') !== stylePreset) {
                    setSelectedImageIndex(0);
                    setPrompt(p);
                    setNegativePrompt(np);
                    if (sp !== undefined) {
                      setStylePreset(sp);
                    }
                    return handleGenerateImage(p, np, sp);
                  }
                }}
              />
            </div>

            <div className='sticky bottom-0'>
              <div
                className={`
                  relative flex flex-col pb-2 border-t border-t-solid-gray-800 items-center justify-center bg-white print:hidden
                `}
              >
                <GenerateImageInput
                  textareaId='generate-image-assistant-input'
                  content={chatContent}
                  loading={loadingChat || generating}
                  onChangeContent={setChatContent}
                  onSend={onSendChat}
                />
              </div>
            </div>
          </div>

          <div className={`shrink-0 ${isRightPanelOpen ? 'w-64 lg:w-96' : ''}`}>
            <div className='sticky top-[calc(var(--header-height))] flex h-[calc(100dvh-var(--header-height))] flex-col'>
              <div
                className={`shrink-0 py-3 pr-3 pl-4 ${isRightPanelOpen ? '' : 'flex justify-center'}`}
              >
                <div
                  className={`flex items-center ${isRightPanelOpen ? 'justify-between' : 'justify-center'}`}
                >
                  {isRightPanelOpen && (
                    <h2 className='text-std-18B-160 lg:text-std-20B-150'>生成結果</h2>
                  )}
                  <Tooltip placement='bottom-end'>
                    <TooltipTrigger asChild>
                      <Button
                        type='button'
                        className='min-w-0! size-11! p-0! hover:border-[3px] hover:bg-white'
                        size='sm'
                        variant='outline'
                        onClick={() => setIsRightPanelOpen((prev) => !prev)}
                        aria-expanded={isRightPanelOpen}
                        aria-controls={isRightPanelOpen ? 'generate-image-right-panel' : undefined}
                      >
                        {isRightPanelOpen ? (
                          <RightPanelCloseIcon
                            className='mx-auto'
                            role='img'
                            aria-label='生成結果を閉じる'
                          />
                        ) : (
                          <RightPanelOpenIcon
                            className='mx-auto'
                            role='img'
                            aria-label='生成結果を開く'
                          />
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent aria-hidden={true}>
                      {isRightPanelOpen ? '生成結果を閉じる' : '生成結果を開く'}
                    </TooltipContent>
                  </Tooltip>
                </div>
              </div>

              {isRightPanelOpen && (
                <div
                  id='generate-image-right-panel'
                  className='flex-1 overflow-y-auto pr-3 pl-4 pb-2 [scrollbar-gutter:stable]'
                >
                  <GeneratedImages
                    generating={generating}
                    selectedImageIndex={selectedImageIndex}
                    setSelectedImageIndex={setSelectedImageIndex}
                  />

                  <Disclosure className='mt-8 relative border-b border-b-solid-gray-536 pb-2'>
                    <DisclosureSummary className='text-std-18B-160'>
                      <h3>詳細設定</h3>
                    </DisclosureSummary>
                    <div className='py-4'>
                      <ImageGeneratorForm
                        loadingChat={loadingChat}
                        generating={generating}
                        selectedImageIndex={selectedImageIndex}
                        setSelectedImageIndex={setSelectedImageIndex}
                        setIsOpenSketch={setIsOpenSketch}
                        setIsOpenMask={setIsOpenMask}
                        generateImage={generateImageWithAnnounce}
                        clearAll={clearAll}
                        onClickRandomSeed={() => onClickRandomSeed(selectedImageIndex)}
                      />
                    </div>
                  </Disclosure>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {liveStatusMessage}
      </div>

      <SketchMaskDialogs
        width={width}
        height={height}
        initImage={initImage}
        maskImage={maskImage}
        isOpenSketch={isOpenSketch}
        isOpenMask={isOpenMask}
        onCloseSketch={() => setIsOpenSketch(false)}
        onCloseMask={() => setIsOpenMask(false)}
        onChangeInitImage={onChangeInitImageBase64}
        onChangeMaskImage={onChangeMaskImageBase64}
      />
    </>
  );
};
