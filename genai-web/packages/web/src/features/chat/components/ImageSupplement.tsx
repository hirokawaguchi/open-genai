import { useRef, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { ImageIcon } from '@/components/ui/icons/ImageIcon';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { useExAppCatalog } from '@/features/exapps/hooks/useExAppCatalog';
import { isCatalogListed } from '@/features/exapps/utils/builtinExApp';
import { createImageSupplement, type ImageSupplementResponse } from '@/lib/chatApi';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';

type Phase = 'loading' | 'ready' | 'none' | 'error';

type Props = {
  chatId: string;
  messageId: string;
  content: string;
  modelId?: string;
};

export const ImageSupplement = (props: Props) => {
  const { chatId, messageId, content, modelId } = props;
  const { apps, loaded } = useExAppCatalog();
  const imageEnabled =
    isUseCaseEnabled('image') && loaded && isCatalogListed('image', apps, loaded);
  const [isOpen, setIsOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>('loading');
  const [image, setImage] = useState('');
  const [errorText, setErrorText] = useState('');
  const cached = useRef<ImageSupplementResponse | null>(null);
  const cachedKey = useRef('');
  const requestSeq = useRef(0);

  if (!imageEnabled) {
    return null;
  }

  const apply = (result: ImageSupplementResponse) => {
    if (result.status === 'ready' && result.image) {
      setImage(result.image);
      setPhase('ready');
      return;
    }
    setPhase('none');
  };

  const open = async () => {
    setIsOpen(true);
    const key = `${chatId}:${messageId}:${content}`;
    if (cachedKey.current === key && cached.current) {
      apply(cached.current);
      return;
    }
    const seq = ++requestSeq.current;
    setPhase('loading');
    setErrorText('');
    try {
      const result = await createImageSupplement(chatId, messageId, modelId);
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
      setErrorText('画像を用意できませんでした。しばらくしてからもう一度開いてください。');
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
        <ImageIcon className='shrink-0' aria-hidden={true} />
        生成画像を見る
      </Button>
      <CustomDialog isOpen={isOpen} onClose={close}>
        <CustomDialogPanel className='max-w-3xl!'>
          <CustomDialogHeader hasClose={true} onClose={close}>
            補足の画像
          </CustomDialogHeader>
          <CustomDialogBody>
            {phase === 'loading' && <ProgressIndicator label='画像を生成しています' />}
            {phase === 'ready' && (
              <img src={image} alt='回答の補足画像' className='mx-auto max-h-[70vh] max-w-full' />
            )}
            {phase === 'none' && <p>画像はありません</p>}
            {phase === 'error' && <p>{errorText}</p>}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </>
  );
};
