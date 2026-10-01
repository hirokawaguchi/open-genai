import { useRef } from 'react';
import { ChatNotificationDialogButton } from '@/features/chat/components/ChatNotificationDialogButton';
import { ModelSelector } from '@/features/chat/components/ModelSelector';
import { SystemPrompt } from '@/features/chat/components/SystemPrompt';
import { useStickyHeader } from '@/features/chat/hooks/useStickyHeader';

type Props = {
  title: string;
  currentSystemContext: string;
  onOpenNotificationDialog: () => void;
  onOpenSystemContextDialog: () => void;
  onOpenPromptListDialog: () => void;
};

export const ChatStickyHeader = (props: Props) => {
  const {
    title,
    currentSystemContext,
    onOpenNotificationDialog,
    onOpenSystemContextDialog,
    onOpenPromptListDialog,
  } = props;

  const sentinelRef = useRef<HTMLDivElement>(null);
  const isSticky = useStickyHeader(sentinelRef);

  return (
    <>
      <div ref={sentinelRef} className='h-px' />
      <div
        className={`
        group/sticky pt-2.5 z-1 lg:data-[is-sticky='true']:sticky lg:data-[is-sticky='true']:top-(--header-height) lg:data-[is-sticky='true']:bg-white
      `}
        data-is-sticky={isSticky}
      >
        <div className='min-w-0 shrink-0 flex flex-col gap-2'>
          <div className='flex items-center justify-start flex-wrap gap-y-2 gap-x-4 lg:gap-x-6 lg:group-data-[is-sticky="true"]/sticky:gap-4'>
            <p
              aria-hidden={true}
              className='hidden min-w-0 truncate text-std-16B-170 lg:group-data-[is-sticky="true"]/sticky:block'
            >
              {title}
            </p>
            <div className='shrink-0'>
              <ModelSelector />
            </div>
            <ChatNotificationDialogButton className='shrink-0' onClick={onOpenNotificationDialog} />
          </div>
          <SystemPrompt
            currentSystemContext={currentSystemContext}
            setShowSystemContextDialog={onOpenSystemContextDialog}
            setShowPromptListDialog={onOpenPromptListDialog}
          />
        </div>
      </div>
    </>
  );
};
