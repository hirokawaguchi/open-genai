import { InvokeExAppHistory } from 'genai-web';
import { ComponentProps, useId, useRef, useState } from 'react';
import { Markdown } from '@/components/Markdown';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Ul } from '@/components/ui/dads/Ul';
import { UpdateIcon } from '@/components/ui/icons/UpdateIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { formatDateTime } from '@/utils/formatDateTime';
import { FileInputItem } from '../types';
import { ExAppArtifactDownloads } from './ExAppArtifactDownloads';
import { ExAppInvokedHistoryDeleteDialog } from './ExAppInvokedHistoryDeleteDialog';
import { ExAppInvokeHistoryItemStatusLabel } from './ExAppInvokeHistoryItemStatusLabel';

type Props = ComponentProps<'details'> & {
  history: InvokeExAppHistory;
  shouldShowConversationHistory: boolean;
  isReloading: boolean;
  onReload: (history: InvokeExAppHistory) => void;
  onDeleted: () => void;
};

export const ExAppInvokedHistoryItem = (props: Props) => {
  const { className, history, shouldShowConversationHistory, isReloading, onReload, onDeleted } =
    props;

  const historyId = useId();

  const copyTextRef = useRef<HTMLDivElement>(null);
  const [shouldShowDeleteDialog, setShouldShowDeleteDialog] = useState(false);

  const getFilesInfo = (files: FileInputItem[]) => {
    return files.map((item) => item.files.map((file) => file.filename).join(', ')).join(', ');
  };

  const parse = (text: string): string => {
    try {
      const parsed = JSON.parse(text === '{}' ? '' : text);
      return parsed === '' ? '' : parsed;
    } catch {
      return `${text}`;
    }
  };
  const parsedOutputs = history.status === 'COMPLETED' ? parse(history.outputs) : '';

  return (
    <>
      <details
        className={`group/accordion border-b border-solid-gray-420 bg-white [--icon-size:calc(20/16*1rem)] desktop:[--icon-size:calc(32/16*1rem)] ${className ?? ''}`}
      >
        <summary
          className={`group/summary relative block rounded-8 py-3 pr-3 pl-[calc(var(--icon-size)+(26/16*1rem))] marker:[content:''] hover:bg-solid-gray-50 focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid desktop:py-4 desktop:pr-4 desktop:pl-[calc(var(--icon-size)+(28/16*1rem))] [&::-webkit-details-marker]:hidden`}
        >
          <span
            className={`absolute top-3.5 left-4 mt-[calc((1lh-var(--icon-size))/2)] inline-flex size-(--icon-size) items-center justify-center rounded-full border border-current bg-white text-blue-1000 group-open/accordion:rotate-180 group-hover/summary:outline-2 group-hover/summary:outline-current group-hover/summary:outline-solid desktop:top-[calc(18/16*1rem)] desktop:left-4`}
          >
            <svg
              aria-hidden={true}
              className='pointer-events-none mt-0.5 size-4 desktop:size-auto'
              width='20'
              height='20'
              viewBox='0 0 20 20'
              fill='none'
            >
              <g>
                <path
                  d='M16.668 5.5L10.0013 12.1667L3.33464 5.5L2.16797 6.66667L10.0013 14.5L17.8346 6.66667L16.668 5.5Z'
                  fill='currentColor'
                />
              </g>
            </svg>
          </span>
          <h3
            id={`history-${historyId}-heading`}
            className='flex items-baseline gap-4 text-std-17N-170 text-solid-gray-800'
          >
            <time dateTime={new Date(Number(history.createdDate)).toISOString()}>
              <span className='sr-only'>実行日時：</span>
              <span className='inline-block min-w-[calc(188/16*1rem)] font-700'>
                {formatDateTime(history.createdDate)}
              </span>
            </time>
            <ExAppInvokeHistoryItemStatusLabel status={history.status} />
          </h3>
        </summary>

        <div className='pt-2 pr-3 pb-4 pl-[calc(var(--icon-size)+(26/16*1rem))] desktop:pb-6'>
          <Disclosure className='w-full rounded-8 border border-solid-gray-420'>
            <DisclosureSummary className='w-full px-4 py-3 text-dns-17B-130'>
              <h4>入力内容</h4>
            </DisclosureSummary>
            <div className='px-4 pt-1 pb-3'>
              <Ul>
                {Object.keys(history.inputs ?? {}).map((key) => {
                  if (key === 'files') {
                    return (
                      <li key={key} className='text-solid-gray-800'>
                        {key}: {getFilesInfo(history.inputs[key])}
                      </li>
                    );
                  } else if (key === 'conversation_histories' && shouldShowConversationHistory) {
                    return null;
                  } else {
                    return (
                      <li key={key} className='text-solid-gray-800'>
                        {key}: {String(history.inputs[key])}
                      </li>
                    );
                  }
                })}
              </Ul>
            </div>
          </Disclosure>
          <Disclosure className='mt-4 w-full rounded-8 border border-solid-gray-420' open>
            <DisclosureSummary className='w-full px-4 py-3 text-dns-17B-130'>
              <h4>出力結果</h4>
            </DisclosureSummary>

            <div className='px-4 py-3'>
              {history.status === 'ERROR' && (
                <p className='text-error-2'>実行中にエラーが発生しました。再度お試しください。</p>
              )}
              {history.status === 'ACCEPTED' && (
                <div>
                  <p>処理を受け付けました。しばらくお待ちください。</p>
                  <LoadingButton
                    className='mt-3 min-w-[calc(134/16*1rem)] justify-start gap-1.5'
                    loading={isReloading}
                    variant='outline'
                    size='sm'
                    type='button'
                    onClick={() => {
                      onReload(history);
                    }}
                  >
                    {!isReloading && <UpdateIcon aria-hidden={true} />}
                    {isReloading ? '更新中...' : '状態を更新'}
                  </LoadingButton>
                </div>
              )}
              {history.status === 'IN_PROGRESS' && (
                <div>
                  <p>{history.progress}</p>
                  <LoadingButton
                    className='mt-3 min-w-[calc(134/16*1rem)] justify-start gap-1.5'
                    loading={isReloading}
                    variant='outline'
                    size='sm'
                    type='button'
                    onClick={() => {
                      onReload(history);
                    }}
                  >
                    {!isReloading && <UpdateIcon aria-hidden={true} />}
                    {isReloading ? '更新中...' : '状態を更新'}
                  </LoadingButton>
                </div>
              )}
              {history.status === 'COMPLETED' && (
                <div>
                  <div ref={copyTextRef}>
                    <Markdown>{parsedOutputs}</Markdown>
                  </div>
                  <div className='mt-1 flex w-full justify-end'>
                    <ButtonCopy text={parsedOutputs} targetRef={copyTextRef} />
                  </div>

                  <ExAppArtifactDownloads artifacts={history.artifacts} />
                </div>
              )}
            </div>
          </Disclosure>
          <div className='relative mt-4 flex min-h-8 flex-col items-center justify-center gap-4 desktop:mt-6 desktop:flex-row'>
            {history.status === 'COMPLETED' && shouldShowConversationHistory && (
              <LoadingButton
                onClick={() => {
                  localStorage.setItem('history', JSON.stringify(history));
                  location.href = `/apps/${history.teamId}/${history.exAppId}`;
                }}
                variant='outline'
                size='lg'
                className='w-60'
              >
                会話を続ける
              </LoadingButton>
            )}
            <Button
              onClick={() => setShouldShowDeleteDialog(true)}
              variant={'text'}
              size={'md'}
              type='button'
              aria-describedby={`history-${historyId}-heading`}
              className='text-error-1! hover:bg-red-50! hover:text-error-2! active:bg-red-50! active:text-error-2! desktop:absolute desktop:right-0'
            >
              履歴を削除
            </Button>
          </div>
        </div>
      </details>

      {shouldShowDeleteDialog && (
        <ExAppInvokedHistoryDeleteDialog
          history={history}
          isOpen={shouldShowDeleteDialog}
          setIsOpen={setShouldShowDeleteDialog}
          onDeleted={() => {
            setShouldShowDeleteDialog(false);
            onDeleted();
          }}
        />
      )}
    </>
  );
};
