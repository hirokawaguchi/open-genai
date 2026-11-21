import { Team } from 'genai-web';
import { useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError } from '@/lib/fetcher';
import { focus } from '@/utils/focus';
import { useDeleteTeam } from '../hooks/useDeleteTeam';

type Props = {
  team?: Team;
  isOpen: boolean;
  onDeleted: (teamId: string) => void;
  onClose: () => void;
};

export const DialogDeleteTeam = (props: Props) => {
  const { team, isOpen, onClose, onDeleted } = props;

  const { deleteTeam } = useDeleteTeam();

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleDelete = async () => {
    if (!team) {
      return;
    }

    try {
      setError('');
      setIsLoading(true);
      await deleteTeam(team.teamId);
      onDeleted(team.teamId);

      focus('team-list-heading');
    } catch (e) {
      if (isApiError(e)) {
        setError((e.data as { error?: string })?.error ?? '');
      } else {
        setError('システムエラーが発生しました。ページをリロードして再度お試しください。');
      }
      focus('server-error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <CustomDialog isOpen={isOpen} onClose={onClose}>
      <CustomDialogPanel>
        <CustomDialogHeader>チームの削除</CustomDialogHeader>
        <CustomDialogBody>
          <p>チーム「{team?.teamName}」を削除しますか？</p>

          <div
            role='alert'
            className='mt-3 flex flex-col gap-1 rounded-6 bg-yellow-50 p-3 text-std-16N-160 text-error-1'
          >
            <p className='font-bold'>⚠ この操作は取り消せません</p>
            <p>
              チームのメンバー・AIアプリ設定に加え、
              <strong>このチーム専用の知識ベース（RAGに登録したドキュメント）も完全に削除</strong>
              されます。
            </p>
          </div>

          {error && (
            <section className='my-4'>
              <h3 id='server-error' className='sr-only' tabIndex={-1}>
                システムエラー
              </h3>
              <div
                className={`mx-auto flex w-full flex-col gap-2 rounded-6 bg-red-50 p-4 text-center text-error-1`}
              >
                <p>{error}</p>
              </div>
            </section>
          )}

          <div className='mt-4 flex justify-between gap-2'>
            <Button data-autofocus variant='text' size='md' onClick={onClose}>
              キャンセル
            </Button>
            <LoadingButton
              variant='solid-fill'
              size='md'
              onClick={() => handleDelete()}
              className='flex min-w-32 items-center justify-center bg-error-1!'
              loading={isLoading}
            >
              {isLoading ? '削除中' : '削除'}
            </LoadingButton>
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
