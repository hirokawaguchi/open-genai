import { useCallback, useRef, useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { DiagramIcon } from '@/components/ui/icons/DiagramIcon';
import { MermaidRenderer } from '@/features/exapp/components/MermaidRenderer';
import { createDiagramSupplement, type DiagramSupplementResponse } from '@/lib/chatApi';

type Phase = 'loading' | 'ready' | 'none' | 'error';

type Props = {
  chatId: string;
  messageId: string;
  content: string;
  modelId?: string;
};

export const DiagramSupplement = (props: Props) => {
  const { chatId, messageId, content, modelId } = props;
  const [isOpen, setIsOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>('loading');
  const [mermaid, setMermaid] = useState('');
  const [errorText, setErrorText] = useState('');
  const cached = useRef<DiagramSupplementResponse | null>(null);
  const cachedKey = useRef('');
  const requestSeq = useRef(0);

  const apply = (result: DiagramSupplementResponse) => {
    if (result.status === 'ready' && result.mermaid) {
      setMermaid(result.mermaid);
      setPhase('ready');
      return;
    }
    setPhase('none');
  };

  const handleRenderError = useCallback(() => {
    setErrorText('図の記法を表示できませんでした。');
    setPhase('error');
  }, []);

  const open = async () => {
    setIsOpen(true);
    const key = `2:${chatId}:${messageId}:${content}`;
    if (cachedKey.current === key && cached.current?.status === 'ready' && cached.current.mermaid) {
      apply(cached.current);
      return;
    }
    const seq = ++requestSeq.current;
    setPhase('loading');
    setErrorText('');
    try {
      const result = await createDiagramSupplement(chatId, messageId, modelId);
      if (seq !== requestSeq.current) {
        return;
      }
      cached.current = result;
      cachedKey.current = key;
      apply(result);
    } catch {
      if (seq !== requestSeq.current) {
        return;
      }
      setErrorText('図を用意できませんでした。しばらくしてからもう一度開いてください。');
      setPhase('error');
    }
  };

  const close = () => {
    requestSeq.current += 1;
    setIsOpen(false);
  };

  return (
    <>
      <Button
        type='button'
        variant='text'
        size='sm'
        className='inline-flex justify-center items-center gap-x-1'
        onClick={() => void open()}
      >
        <DiagramIcon className='shrink-0' aria-hidden={true} />
        図を見る
      </Button>
      <CustomDialog isOpen={isOpen} onClose={close}>
        <CustomDialogPanel className='max-w-4xl!'>
          <CustomDialogHeader hasClose={true} onClose={close}>
            補足の図
          </CustomDialogHeader>
          <CustomDialogBody className='max-h-[70vh] overflow-auto'>
            {phase === 'loading' && <ProgressIndicator label='図を用意しています' />}
            {phase === 'ready' && <MermaidRenderer code={mermaid} onError={handleRenderError} />}
            {phase === 'none' && <p>図はありません</p>}
            {phase === 'error' && <p>{errorText}</p>}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </>
  );
};
