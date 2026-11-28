import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { NotebookSourceHandoff } from '@/open-genai/notebook/NotebookSourceHandoff';
import { useMyTenants } from '@/open-genai/tenants/useTenants';

type Props = {
  text: string;
};

export const WhisperHandoff = (props: Props) => {
  const { text } = props;
  const navigate = useNavigate();
  const { tenants, activeTenantId, isLoading } = useMyTenants();
  const tenant = tenants.find((item) => item.tenantId === activeTenantId);
  const features = tenant?.features ?? {};
  const chatOn = !isLoading && features.chat !== false;
  const notebookOn = !isLoading && features.notebook !== false;

  if (!text.trim() || (!chatOn && !notebookOn)) {
    return null;
  }

  return (
    <>
      {chatOn ? (
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={() => navigate('/chat', { state: { content: text } })}
        >
          チャットで扱う
        </Button>
      ) : null}
      <NotebookSourceHandoff text={text} filename='文字起こし.md' titlePrefix='文字起こし' />
    </>
  );
};
