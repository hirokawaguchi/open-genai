import { Link, useParams } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { linkDefaultStyle } from '@/components/ui/dads/Link';
import { decomposeId } from '@/utils/decomposeId';
import { formatDateTime } from '@/utils/formatDateTime';
import { getChatHistoryLink, getUsecaseLabel, resolveChatUsecase } from '@/utils/usecasePath';
import { useChatHistorySidebar } from '../hooks/useChatHistorySidebar';

export const ChatHistorySidebar = () => {
  const { displayedChats, isLoading } = useChatHistorySidebar();
  const { chatId } = useParams();

  const isInitialLoading = isLoading && displayedChats.length === 0;
  const isEmpty = !isLoading && displayedChats.length === 0;

  return (
    <nav
      className='grid grid-cols-1 grid-rows-[auto_1fr_auto] gap-1 min-h-0'
      aria-labelledby='side-chat-history-heading'
    >
      <h2 id='side-chat-history-heading' className='text-std-20B-150'>
        利用履歴
      </h2>

      {isInitialLoading && (
        <div className='mt-3 flex flex-col gap-2'>
          {[...Array(5)].map((_, idx) => (
            <div key={idx} className='h-8 w-full animate-pulse rounded-4 bg-blue-50' />
          ))}
        </div>
      )}

      {isEmpty && <p className='mt-3 text-std-16N-170 text-solid-gray-600'>利用履歴はありません</p>}

      {displayedChats.length > 0 && (
        <>
          <ul className='flex flex-col min-h-0 overflow-y-auto [scrollbar-gutter:stable]'>
            {displayedChats.map((chat) => {
              const decomposedChatId = decomposeId(chat.chatId);
              if (!decomposedChatId) return null;
              const isCurrent = decomposedChatId === chatId;
              const usecase = resolveChatUsecase(chat);
              return (
                <li className='border-b border-b-solid-gray-420 text-std-16N-175' key={chat.chatId}>
                  <Link
                    to={getChatHistoryLink(chat)}
                    aria-current={isCurrent ? 'page' : undefined}
                    className="group/history flex flex-col gap-1 items-start py-3 pl-2 pr-1.5 hover:bg-solid-gray-50 aria-[current='page']:bg-blue-50 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-black focus-visible:outline-solid focus-visible:rounded-4 focus-visible:bg-yellow-300 focus-visible:ring-[calc(6/16*1rem)] focus-visible:ring-yellow-300 focus-visible:ring-inset"
                  >
                    <time dateTime={new Date(Number(chat.createdDate)).toISOString()}>
                      {formatDateTime(chat.createdDate)}
                    </time>
                    <span className='text-dns-14N-130 text-solid-gray-600'>
                      {getUsecaseLabel(usecase)}
                    </span>
                    <p
                      className={`${linkDefaultStyle} group-hover/history:text-blue-900 group-hover/history:decoration-[calc(3/16*1rem)] group-aria-[current='page']/history:font-bold group-aria-[current='page']/history:text-blue-1000!`}
                    >
                      {chat.title || '無題'}
                    </p>
                  </Link>
                </li>
              );
            })}
          </ul>
          <Button
            asChild
            variant='outline'
            size='lg'
            className='mt-6 inline-flex justify-center items-center w-full'
          >
            <Link to='/history'>全ての利用履歴を見る</Link>
          </Button>
        </>
      )}
    </nav>
  );
};
