import { Link } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { ProcedureSharePanel } from './ProcedureSharePanel';

type Props = {
  procedureId: string;
  name: string;
  status: string;
  publicUrl?: string | null;
  canEdit?: boolean;
  submitting?: boolean;
  republish?: boolean;
  onPublish?: () => void | Promise<void>;
  onClose?: () => void | Promise<void>;
};

export const ProcedureReceptionActions = ({
  procedureId,
  name,
  status,
  publicUrl,
  canEdit,
  submitting,
  republish,
  onPublish,
  onClose,
}: Props) => {
  const published = status === 'published';
  return (
    <div className='flex flex-col gap-2'>
      {published && publicUrl ? (
        <p className='text-dns-14N-130 text-solid-gray-600'>公開 URL: {publicUrl}</p>
      ) : null}
      <div className='flex flex-wrap gap-2'>
        {published ? (
          <Link to={`/patchform/apply/${procedureId}`} className='inline-flex'>
            <Button type='button' variant='solid-fill' size='sm'>
              庁内から申請する
            </Button>
          </Link>
        ) : null}
        {canEdit && published && onClose ? (
          <Button
            type='button'
            variant='outline'
            size='sm'
            aria-disabled={submitting}
            onClick={() => void onClose()}
          >
            受付を終了
          </Button>
        ) : null}
        {canEdit && !published && onPublish ? (
          <Button
            type='button'
            variant='solid-fill'
            size='sm'
            aria-disabled={submitting}
            onClick={() => void onPublish()}
          >
            {republish ? '再公開する' : '公開する'}
          </Button>
        ) : null}
      </div>
      {published ? <ProcedureSharePanel procedureId={procedureId} name={name} /> : null}
    </div>
  );
};
