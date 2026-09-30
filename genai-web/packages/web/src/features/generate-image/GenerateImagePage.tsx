import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { mutate } from 'swr';
import { PageTitle } from '@/components/PageTitle';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { ChatHistorySidebar } from '@/features/chat/components/ChatHistorySidebar';
import { useGenerateImage } from '@/features/generate-image/hooks/useGenerateImage';
import { useReset } from '@/features/generate-image/hooks/useReset';
import { useSetDefaultValues } from '@/features/generate-image/hooks/useSetDefaultValues';
import { useGenerateImageStore } from '@/features/generate-image/stores/useGenerateImageStore';
import { formatLocalSdUnavailableMessage } from '@/features/generate-image/utils/formatLocalSdUnavailable';
import { useChat } from '@/hooks/useChat';
import { useSelectedModel } from '@/hooks/useSelectedModel';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { createChat, createMessages, predict, saveImageResult, updateTitle } from '@/lib/chatApi';
import { pageFileUrl } from '@/lib/fileUrl';
import { ApiError } from '@/lib/fetcher';
import { findModelByModelId, MODELS } from '@/models';
import { decomposeId } from '@/utils/decomposeId';
import { newId } from '@/utils/uuid';
import { ImageComposer } from './components/ImageComposer';
import { ImageThread } from './components/ImageThread';
import { buildDirectImageAssistantContent } from './utils/ensureImagePersistTarget';
import { buildImageTurns } from './utils/imageThread';
import { fileUrlToBase64, findLatestImageResultMessage } from './utils/imageResultExtraData';

const description = 'プロンプトから資料用の挿絵やイメージ案を作成';

const readPixels = (text: string) => {
  const match = text.match(/(\d+)\s*x\s*(\d+)/i);
  if (!match) {
    return null;
  }
  return { width: Number(match[1]), height: Number(match[2]) };
};

export const GenerateImagePage = () => {
  const { title: appName, documentTitle } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    'image',
    '画像を生成',
  );
  const { usecase, chatId } = useUsecasePath();
  const navigate = useNavigate();
  const { rawMessages, loadingMessages, clear: clearChat, chatTitle } = useChat(usecase, chatId);
  const { generateImage } = useGenerateImage();
  const { selectedModelId } = useSelectedModel();
  const { imageGenModelIds } = MODELS;
  useReset();
  useSetDefaultValues();

  const [draft, setDraft] = useState('');
  const [attachmentUrl, setAttachmentUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [refining, setRefining] = useState(false);
  const [refineError, setRefineError] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  const [pending, setPending] = useState<{
    prompt: string;
    sourceUrl?: string;
    resultUrl?: string;
    error?: string;
  } | null>(null);
  const sentCountRef = useRef(0);
  const threadRef = useRef<HTMLDivElement>(null);

  const {
    imageGenModelId,
    resolution,
    stylePreset,
    step,
    cfgScale,
    imageStrength,
    clear,
    setImageGenModelId,
  } = useGenerateImageStore();

  useEffect(() => {
    const node = threadRef.current;
    const latest = node?.querySelector<HTMLElement>('[data-latest="true"]');
    if (!node || !latest) {
      return;
    }
    const peek = 120;
    node.scrollTop = Math.max(0, latest.offsetTop - peek);
  }, [rawMessages, pending, loadingMessages]);

  useEffect(() => {
    if (!pending || pending.error || busy) {
      return;
    }
    const userCount = rawMessages.filter((message) => message.role === 'user').length;
    const turns = buildImageTurns(rawMessages);
    const last = turns[turns.length - 1];
    if (userCount > sentCountRef.current && last?.images.length) {
      setPending(null);
    }
  }, [rawMessages, pending, busy]);

  const onNewSession = () => {
    const nextImageModel = imageGenModelId || imageGenModelIds[0] || '';
    clear();
    if (nextImageModel) {
      setImageGenModelId(nextImageModel);
    }
    clearChat();
    setDraft('');
    setAttachmentUrl('');
    setPending(null);
    setRefineError('');
    navigate('/image', { state: { shouldReset: true } });
  };

  const onRefine = async () => {
    const text = draft.trim();
    const model = findModelByModelId(selectedModelId);
    if (!text || !model) {
      return;
    }
    setRefining(true);
    setRefineError('');
    try {
      const rewritten = await predict({
        id: newId(),
        model,
        messages: [
          {
            role: 'user',
            content:
              '次の指示を、画像生成向けの具体的なプロンプトに書き直してください。説明や前置きは書かず、プロンプト文だけを返してください。\n\n' +
              text,
          },
        ],
      });
      setDraft(rewritten.trim());
    } catch {
      setRefineError('プロンプトを整えられませんでした。');
    } finally {
      setRefining(false);
    }
  };

  const onSend = async () => {
    const prompt = draft.trim();
    if (!prompt || busy) {
      return;
    }
    const size =
      readPixels(resolution.value) ??
      readPixels(resolution.label) ?? { width: 1024, height: 1024 };
    sentCountRef.current = rawMessages.filter((message) => message.role === 'user').length;
    setBusy(true);
    setRefineError('');
    let source = attachmentUrl;
    setPending({ prompt, sourceUrl: source || undefined });
    try {
      if (!source) {
        const previous = findLatestImageResultMessage(rawMessages);
        const previousImages = previous?.result.images ?? [];
        const previousUrl = previousImages[previousImages.length - 1]?.fileUrl;
        if (previousUrl) {
          setPending({ prompt, sourceUrl: pageFileUrl(previousUrl) });
          try {
            const previousBase64 = await fileUrlToBase64(previousUrl);
            source = `data:image/png;base64,${previousBase64}`;
          } catch {
            setPending({
              prompt,
              sourceUrl: pageFileUrl(previousUrl),
              error: '前の画像を読み込めなかったので、続きとして加工できませんでした。',
            });
            return;
          }
        }
      }
      const image = await generateImage(
        {
          textPrompt: [{ text: prompt, weight: 1 }],
          width: size.width,
          height: size.height,
          step,
          cfgScale,
          seed: -1,
          stylePreset: stylePreset || undefined,
          initImage: source || undefined,
          imageStrength,
        },
        MODELS.imageGenModels.find((model) => model.modelId === imageGenModelId),
      );

      let targetId = chatId;
      let created = false;
      if (!targetId) {
        const { chat } = await createChat({ usecase });
        targetId = decomposeId(chat.chatId) ?? chat.chatId.replace(/^chat#/, '');
        created = true;
      }
      const assistantId = newId();
      await createMessages(targetId, {
        messages: [
          {
            messageId: newId(),
            role: 'user',
            content: prompt,
            usecase,
          },
          {
            messageId: assistantId,
            role: 'assistant',
            content: buildDirectImageAssistantContent(prompt, ''),
            usecase,
          },
        ],
      });
      await saveImageResult(targetId, assistantId, {
        images: [image],
        sourceImage: source || undefined,
        meta: {
          prompt,
          negativePrompt: '',
          stylePreset,
          seeds: [],
          step,
          cfgScale,
          imageSample: 1,
        },
      });
      if (created) {
        await updateTitle(targetId, prompt.slice(0, 40));
      }
      await mutate(`chats/${targetId}/messages`);
      await mutate((key) => typeof key === 'string' && key.startsWith('chats'), undefined, {
        revalidate: true,
      });
      setDraft('');
      setAttachmentUrl('');
      setPending({
        prompt,
        sourceUrl: source || undefined,
        resultUrl: `data:image/png;base64,${image}`,
      });
      if (created) {
        navigate(`${usecase}/${targetId}`, { replace: true });
      }
    } catch (error) {
      const data = error instanceof ApiError ? (error.data as { message?: string; code?: string }) : undefined;
      const message =
        data?.code === 'local_sd_unavailable'
          ? formatLocalSdUnavailableMessage(imageGenModelIds)
          : (data?.message ?? '画像を生成できませんでした。');
      setPending({ prompt, sourceUrl: source || undefined, error: message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) flex-col overflow-hidden px-4 py-2 lg:px-6'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            chatTitle ? { label: appName, to: '/image' } : { label: appName },
            ...(chatTitle ? [{ label: chatTitle }] : []),
          ]}
        />
        <div className='mt-1 flex min-w-0 items-center gap-3'>
          <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{appName}</h1>
          <p className='min-w-0 flex-1 truncate text-dns-14N-130 text-solid-gray-600' title={description}>
            {description}
          </p>
          <Button type='button' variant='outline' size='sm' onClick={() => setHelpOpen(true)}>
            使い方
          </Button>
        </div>

        <div className='mt-2 flex min-h-0 flex-1 flex-col gap-3 lg:flex-row lg:gap-4'>
          <div className='order-2 flex min-h-0 min-w-0 flex-1 flex-col lg:order-1'>
            <div ref={threadRef} className='min-h-0 flex-1 overflow-y-scroll'>
              {loadingMessages && rawMessages.length === 0 && (
                <p className='px-1 py-4 text-dns-14N-130 text-solid-gray-600'>読み込み中...</p>
              )}
              <ImageThread
                messages={rawMessages}
                pending={pending}
                generating={busy && !refining}
              />
            </div>
            <ImageComposer
              draft={draft}
              attachmentUrl={attachmentUrl}
              continuing={!attachmentUrl && Boolean(findLatestImageResultMessage(rawMessages))}
              busy={busy}
              refining={refining}
              refineError={refineError}
              onChangeDraft={(value) => {
                setDraft(value);
                if (refineError) {
                  setRefineError('');
                }
              }}
              onAttach={setAttachmentUrl}
              onClearAttachment={() => setAttachmentUrl('')}
              onRefine={onRefine}
              onSend={onSend}
            />
          </div>
          <aside className='order-1 flex max-h-28 shrink-0 flex-col gap-2 overflow-y-auto lg:order-2 lg:max-h-none lg:w-56 xl:w-64'>
            <Button variant='solid-fill' size='lg' className='w-full' onClick={onNewSession}>
              新規セッション
            </Button>
            <div className='min-h-0 flex-1 overflow-y-auto'>
              <ChatHistorySidebar scope='image' />
            </div>
          </aside>
        </div>
      </div>

      {helpOpen && (
        <div className='fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-6' role='presentation'>
          <div
            role='dialog'
            aria-modal='true'
            aria-labelledby='image-help-title'
            className='mt-16 w-full max-w-lg rounded-8 bg-white p-5 shadow-lg'
          >
            <h2 id='image-help-title' className='text-std-18B-160'>
              使い方
            </h2>
            <ul className='mt-3 list-disc space-y-2 pl-5 text-std-16N-170'>
              <li>作りたい内容を書いて送信すると、その文の下に画像が残ります。</li>
              <li>「プロンプト」は文章を整えるモデル、「画像」は描くモデルです。</li>
              <li>「プロンプトを整える」は入力欄を書き換えるだけで、会話には残りません。</li>
              <li>同じセッションで続けて送ると、直前の画像を引き継いで加工します。履歴から開いたあとも同じです。</li>
              <li>別の画像を添付したときは、その画像を加工します。まったく新しい絵にするときは「新規セッション」を使います。</li>
              <li>サイズと雰囲気は「設定」を開くと変えられます。</li>
            </ul>
            <div className='mt-4 flex justify-end'>
              <Button type='button' variant='outline' size='sm' onClick={() => setHelpOpen(false)}>
                閉じる
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
