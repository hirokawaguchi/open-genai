import { ExApp } from 'genai-web';
import { useEffect, useState } from 'react';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { ExAppInvokedHistoryItem } from '@/features/exapp/components/ExAppInvokedHistoryItem';
import { useFetchExAppHistory } from '@/features/exapp/hooks/useFetchInvokedExAppHistory';
import { useFocusNewItemOnLoadMore } from '@/hooks/useFocusNewItemOnLoadMore';
import { useExAppInvokedHistories } from '../hooks/useExAppInvokedHistories';

type Props = {
  exApp: ExApp;
};

export const ExAppInvokedHistories = (props: Props) => {
  const { exApp } = props;
  const { fetchExAppHistory } = useFetchExAppHistory();
  const [reloadingHistories, setReloadingHistories] = useState<string[]>([]);

  const { histories, hasMore, isValidating, loadMore, mutate } = useExAppInvokedHistories(
    exApp.teamId,
    exApp.exAppId,
  );

  useEffect(() => {
    return () => {
      mutate();
    };
  }, [mutate]);

  const hasPending = histories.some(
    (history) => history.status === 'IN_PROGRESS' || history.status === 'ACCEPTED',
  );

  useEffect(() => {
    if (!hasPending) {
      return;
    }
    const id = window.setInterval(() => {
      void mutate();
    }, 4000);
    return () => window.clearInterval(id);
  }, [hasPending, mutate]);

  const { listRef, loadMoreWithFocus } = useFocusNewItemOnLoadMore<HTMLDivElement>({
    itemsLength: histories.length,
    focusSelector: 'summary',
  });

  if (histories.length === 0) {
    return <p>利用履歴はありません</p>;
  }

  return (
    <>
      <div ref={listRef} className='flex flex-col'>
        {histories.map((history) => {
          return (
            <ExAppInvokedHistoryItem
              key={`${history.teamId}-${history.exAppId}-${history.userId}-${history.createdDate}`}
              history={history}
              shouldShowConversationHistory={exApp.placeholder.includes('conversation_history')}
              isReloading={
                reloadingHistories.find((id) => id === history.createdDate) !== undefined
              }
              onReload={async (history) => {
                try {
                  setReloadingHistories((prev) => [...prev, history.createdDate]);
                  const updatedHistory = await fetchExAppHistory(history);
                  if (!updatedHistory) {
                    return;
                  }
                  await mutate();
                } catch {
                  console.error('Failed to reload history');
                } finally {
                  setReloadingHistories((prev) => prev.filter((id) => id !== history.createdDate));
                }
              }}
              onDeleted={() => mutate()}
            />
          );
        })}
      </div>

      {hasMore && histories.length > 0 && (
        <LoadingButton
          loading={isValidating}
          onClick={() => loadMoreWithFocus(loadMore)}
          className='mt-5'
          variant='outline'
          size='md'
          type='button'
        >
          {isValidating ? '読み込み中' : 'さらに履歴を読み込む'}
        </LoadingButton>
      )}
    </>
  );
};
