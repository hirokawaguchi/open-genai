import { useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { useDeleteExAppInvokeHistory } from '../hooks/useDeleteExAppInvokeHistory';
import { ExAppConversation } from '../hooks/useExAppConversations';

type Props = {
  conversation: ExAppConversation;
  teamId: string;
  exAppId: string;
  isOpen: boolean;
  setIsOpen(isOpen: boolean): void;
  onDeleted: (conversation: ExAppConversation) => void;
};

export const ExAppConversationDeleteDialog = (props: Props) => {
  const { conversation, teamId, exAppId, isOpen, setIsOpen, onDeleted } = props;

  const { deleteConversation } = useDeleteExAppInvokeHistory();
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState('');

  return (
    <CustomDialog isOpen={isOpen} onClose={() => setIsOpen(false)}>
      <CustomDialogPanel>
        <CustomDialogHeader>会話の削除</CustomDialogHeader>
        <CustomDialogBody>
          <p>
            会話
            <strong className='font-700'>「{conversation.title}」</strong>
            を削除しますか？この操作は取り消せません。
          </p>
          {error && <p className='mt-2 text-dns-16N-130 text-error-1'>{error}</p>}

          <div className='relative mt-4 flex justify-between gap-2 pb-2 lg:mt-6'>
            <Button data-autofocus variant='text' size='md' onClick={() => setIsOpen(false)}>
              キャンセル
            </Button>
            <Button
              variant='solid-fill'
              size='md'
              aria-disabled={isDeleting ? 'true' : undefined}
              onClick={async () => {
                setIsDeleting(true);
                setError('');
                try {
                  await deleteConversation(teamId, exAppId, conversation.sessionId);
                  onDeleted(conversation);
                } catch {
                  setError('削除に失敗しました。時間をおいて再度お試しください。');
                } finally {
                  setIsDeleting(false);
                }
              }}
              className='flex items-center justify-center bg-error-1! hover:bg-error-2!'
            >
              {isDeleting ? (
                <>
                  <span className='mr-2 size-4 animate-spin rounded-full border-2 border-white border-t-transparent'></span>
                  削除中
                </>
              ) : (
                <>削除</>
              )}
            </Button>
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
