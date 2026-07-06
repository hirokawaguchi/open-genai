import type { ShownMessage } from 'genai-web';
import { useEffect, useState } from 'react';
import { FileCard } from '@/features/chat/components/FileCard';
import { ZoomUpImage } from '@/features/chat/components/ZoomUpImage';
import { ZoomUpVideo } from '@/features/chat/components/ZoomUpVideo';
import { useFiles } from '@/hooks/useFiles';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useTyping } from '@/hooks/useTyping';

type Props = {
  chatContent: ShownMessage;
};

export const UserMessage = ({ chatContent }: Props) => {
  const { usecase } = useUsecasePath();
  const { getFileDownloadSignedUrl } = useFiles(usecase);

  const { typingTextOutput } = useTyping(false, chatContent.content);

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
  }, [chatContent]);

  return (
    <article className='border border-transparent bg-solid-gray-50 p-4 rounded-12 lg:px-6'>
      <div className='flex w-full max-w-[calc(1024/16*1rem)] flex-col justify-between'>
        <div className='flex w-full gap-4'>
          <h2 className='sr-only'>あなたの質問</h2>

          <div className='mt-1 w-full pr-8 lg:pr-14'>
            {chatContent.extraData && (
              <div className='-mt-1 mb-2 flex flex-wrap gap-2 empty:mt-0! empty:mb-0!'>
                {chatContent.extraData.map((data, idx) => {
                  if (data.type === 'image') {
                    return (
                      <ZoomUpImage
                        key={`${chatContent.id}-${data.type}-${idx}`}
                        src={signedUrls[idx]}
                        size='md'
                        loading={!signedUrls[idx]}
                        filename={data.name}
                        alt={`アップロードした画像: ${data.name}`}
                      />
                    );
                  } else if (data.type === 'file') {
                    return (
                      <FileCard
                        key={`${chatContent.id}-${data.type}-${idx}`}
                        filename={data.name}
                        filetype={data.name.split('.').pop() as string}
                        url={signedUrls[idx]}
                        loading={!signedUrls[idx]}
                        size='md'
                      />
                    );
                  } else if (data.type === 'video') {
                    return (
                      <ZoomUpVideo
                        key={`${chatContent.id}-${data.type}-${idx}`}
                        filename={data.name}
                        src={signedUrls[idx]}
                        size='md'
                      />
                    );
                  }
                })}
              </div>
            )}
            <div className='whitespace-pre-wrap'>{typingTextOutput}</div>
          </div>
        </div>
      </div>
    </article>
  );
};
