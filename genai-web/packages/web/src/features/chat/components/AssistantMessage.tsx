import type { ShownMessage } from 'genai-web';
import { useEffect, useRef, useState } from 'react';
import { Markdown } from '@/components/Markdown';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { ReplayIcon } from '@/components/ui/icons/ReplayIcon';
import { FileCard } from '@/features/chat/components/FileCard';
import { ZoomUpImage } from '@/features/chat/components/ZoomUpImage';
import { ZoomUpVideo } from '@/features/chat/components/ZoomUpVideo';
import { useFiles } from '@/hooks/useFiles';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useTyping } from '@/hooks/useTyping';

type Props = {
  idx?: number;
  chatContent: ShownMessage;
  loading?: boolean;
  allowRetry?: boolean;
  retryGeneration?: () => void;
};

export const AssistantMessage = ({
  idx,
  chatContent,
  loading,
  allowRetry,
  retryGeneration,
}: Props) => {
  const { usecase } = useUsecasePath();
  const { getFileDownloadSignedUrl } = useFiles(usecase);
  const copyTextRef = useRef<HTMLDivElement>(null);

  const { typingTextOutput } = useTyping(loading, chatContent.content);

  const [signedUrls, setSignedUrls] = useState<string[]>([]);

  useEffect(() => {
    if (chatContent.extraData) {
      setSignedUrls(new Array(chatContent.extraData.length).fill(undefined));
      Promise.all(
        chatContent.extraData.map(async (file) => {
          if (file.source.type === 's3') {
            return await getFileDownloadSignedUrl(file.source.data, true);
          } else {
            return file.source.data;
          }
        }),
      ).then((results) => setSignedUrls(results));
    } else {
      setSignedUrls([]);
    }
  }, [chatContent.extraData, getFileDownloadSignedUrl]);

  return (
    <article className='border border-solid-gray-420 bg-white p-4 rounded-12 lg:px-6'>
      <div className='flex w-full max-w-[calc(1024/16*1rem)] flex-col justify-between'>
        <div className='flex w-full gap-4'>
          <h2 className='sr-only'>AIの回答</h2>

          <div className='mt-1 w-full'>
            {chatContent.trace && (
              <details className='mb-2 cursor-pointer rounded-sm border p-2'>
                <summary className='text-sm'>
                  <div className='inline-flex gap-1'>
                    トレース
                    {loading && !chatContent.content && (
                      <div className='size-5 animate-spin rounded-full border-4 border-blue-500 border-t-transparent' />
                    )}
                  </div>
                </summary>
                <Markdown prefix={`${idx}-trace`}>{chatContent.trace}</Markdown>
              </details>
            )}
            {chatContent.extraData && (
              <div className='-mt-1 mb-2 flex flex-wrap gap-2 empty:mt-0! empty:mb-0!'>
                {chatContent.extraData.map((data, dataIdx) => {
                  if (data.type === 'image') {
                    return (
                      <ZoomUpImage
                        key={`${chatContent.id}-${data.type}-${dataIdx}`}
                        src={signedUrls[dataIdx]}
                        size='md'
                        loading={!signedUrls[dataIdx]}
                        filename={data.name}
                        alt={`アップロードした画像: ${data.name}`}
                      />
                    );
                  } else if (data.type === 'file') {
                    return (
                      <FileCard
                        key={`${chatContent.id}-${data.type}-${dataIdx}`}
                        filename={data.name}
                        filetype={data.name.split('.').pop() as string}
                        url={signedUrls[dataIdx]}
                        loading={!signedUrls[dataIdx]}
                        size='md'
                      />
                    );
                  } else if (data.type === 'video') {
                    return (
                      <ZoomUpVideo
                        key={`${chatContent.id}-${data.type}-${dataIdx}`}
                        filename={data.name}
                        src={signedUrls[dataIdx]}
                        size='md'
                      />
                    );
                  }
                })}
              </div>
            )}
            <div ref={copyTextRef}>
              <Markdown prefix={`${idx}`}>{typingTextOutput}</Markdown>
            </div>
            {loading && <ProgressIndicator className='my-0.5' />}

            <div className='mt-2 text-right text-std-16N-175 text-solid-gray-536 lg:mb-0'>
              {chatContent.llmType}
            </div>
          </div>
        </div>

        <div className='mt-1 flex items-start justify-end gap-0.5 print:hidden'>
          {!loading && (
            <>
              {allowRetry && (
                <Button
                  variant='text'
                  size='sm'
                  className='inline-flex justify-center items-center gap-x-1'
                  onClick={() => retryGeneration?.()}
                >
                  <ReplayIcon className='shrink-0' aria-hidden={true} />
                  再生成
                </Button>
              )}
              <ButtonCopy
                className='mr-0.5'
                text={chatContent.content || ''}
                targetRef={copyTextRef}
              />
            </>
          )}
        </div>
      </div>
    </article>
  );
};
