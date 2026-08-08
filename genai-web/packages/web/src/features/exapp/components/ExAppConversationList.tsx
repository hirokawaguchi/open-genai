import { useState } from 'react';
import { formatDateTime } from '@/utils/formatDateTime';
import { ExAppConversation } from '../hooks/useExAppConversations';

type Props = {
  conversations: ExAppConversation[];
  // 現在表示中の会話（sessionId）。一覧上でハイライトする。
  activeSessionId: string;
  onSelect: (conversation: ExAppConversation) => void;
};

// チャット画面の「過去の会話」一覧。sessionId ごとにまとめた会話を選ぶと
// ExAppChat 側で復元される。会話が 1 件も無いときは何も表示しない。
export const ExAppConversationList = ({ conversations, activeSessionId, onSelect }: Props) => {
  const [open, setOpen] = useState(false);

  if (conversations.length === 0) {
    return null;
  }

  return (
    <div className='rounded-8 border border-solid-gray-420'>
      <button
        type='button'
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className='flex w-full items-center justify-between rounded-8 px-4 py-3 text-left hover:bg-solid-gray-50'
      >
        <span className='text-std-16B-160 text-solid-gray-800'>
          過去の会話（{conversations.length}）
        </span>
        <svg
          aria-hidden={true}
          className={`size-4 text-blue-1000 transition-transform ${open ? 'rotate-180' : ''}`}
          width='20'
          height='20'
          viewBox='0 0 20 20'
          fill='none'
        >
          <path
            d='M16.668 5.5L10.0013 12.1667L3.33464 5.5L2.16797 6.66667L10.0013 14.5L17.8346 6.66667L16.668 5.5Z'
            fill='currentColor'
          />
        </svg>
      </button>

      {open && (
        <ul className='max-h-[40vh] overflow-y-auto border-t border-solid-gray-420'>
          {conversations.map((conversation) => {
            const isActive = conversation.sessionId === activeSessionId;
            return (
              <li
                key={conversation.sessionId}
                className='border-b border-solid-gray-420 last:border-b-0'
              >
                <button
                  type='button'
                  onClick={() => onSelect(conversation)}
                  aria-current={isActive}
                  className={`flex w-full flex-col gap-0.5 px-4 py-3 text-left hover:bg-blue-50 ${
                    isActive ? 'bg-blue-50' : ''
                  }`}
                >
                  <span className='line-clamp-1 text-std-16N-170 text-solid-gray-800'>
                    {conversation.title}
                  </span>
                  <span className='text-dns-14N-130 text-solid-gray-536'>
                    {formatDateTime(conversation.updatedAt)}・{conversation.turnCount}往復
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};
