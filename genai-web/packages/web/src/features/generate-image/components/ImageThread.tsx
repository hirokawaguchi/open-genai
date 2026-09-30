import type { ShownMessage } from 'genai-web';
import { pageFileUrl } from '@/lib/fileUrl';
import { buildImageTurns } from '../utils/imageThread';

type PendingTurn = {
  prompt: string;
  sourceUrl?: string;
  resultUrl?: string;
  error?: string;
};

type Props = {
  messages: ShownMessage[];
  pending: PendingTurn | null;
  generating: boolean;
};

export const ImageThread = ({ messages, pending, generating }: Props) => {
  const turns = buildImageTurns(messages);
  const last = turns[turns.length - 1];
  const showPending = Boolean(
    pending &&
      !(
        pending.resultUrl &&
        !pending.error &&
        last &&
        last.prompt === pending.prompt &&
        last.images.length > 0
      ),
  );
  const empty = turns.length === 0 && !showPending;

  const latestIndex = turns.length - 1;

  return (
    <div className='flex flex-col gap-6 px-1 py-4'>
      {empty && (
        <p className='text-std-16N-170 text-solid-gray-600'>
          作りたい画像を下の欄に書いて送信してください。画像を添付すると、その画像を加工します。
        </p>
      )}
      {turns.map((turn, index) => (
        <article
          key={turn.key}
          data-latest={index === latestIndex && !showPending ? 'true' : undefined}
          className={`flex flex-col items-start gap-3 ${index > 0 ? 'border-t border-solid-gray-200 pt-4' : ''}`}
        >
          {index > 0 && index === latestIndex && !showPending && (
            <p className='text-dns-14N-130 text-solid-gray-600'>
              前の画像はこの上に続いています。上にスクロールすると見られます。
            </p>
          )}
          <p className='whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'>{turn.prompt}</p>
          {turn.sourceUrl && (
            <img
              src={turn.sourceUrl}
              alt='加工前の画像'
              className='h-auto max-h-40 w-auto max-w-full rounded-8 border border-solid-gray-300 object-contain'
            />
          )}
          <div className='flex flex-wrap gap-3'>
            {turn.images.map((image) => (
              <img
                key={image.src}
                src={image.src}
                alt={turn.prompt}
                className='h-auto max-h-96 w-auto max-w-full self-start rounded-8 object-contain'
              />
            ))}
          </div>
        </article>
      ))}
      {showPending && pending && (
        <article
          data-latest='true'
          className='flex flex-col items-start gap-3 border-t border-solid-gray-200 pt-4'
        >
          <p className='whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'>{pending.prompt}</p>
          {pending.sourceUrl && (
            <img
              src={pageFileUrl(pending.sourceUrl)}
              alt='加工前の画像'
              className='h-auto max-h-40 w-auto max-w-full rounded-8 border border-solid-gray-300 object-contain'
            />
          )}
          {pending.resultUrl && (
            <img
              src={pending.resultUrl}
              alt={pending.prompt}
              className='h-auto max-h-96 w-auto max-w-full self-start rounded-8 object-contain'
            />
          )}
          {generating && !pending.resultUrl && (
            <p className='text-dns-14N-130 text-solid-gray-600'>画像を生成しています...</p>
          )}
          {pending.error && (
            <p className='text-std-16N-170 text-error-1' role='alert'>
              {pending.error}
            </p>
          )}
        </article>
      )}
    </div>
  );
};
