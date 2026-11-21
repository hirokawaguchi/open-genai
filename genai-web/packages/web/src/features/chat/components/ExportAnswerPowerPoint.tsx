import { useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { Textarea } from '@/components/ui/dads/Textarea';
import { PresentationIcon } from '@/components/ui/icons/PresentationIcon';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import {
  draftSlideMarkdown,
  embedMermaidFences,
  splitDeckTitle,
  startPptxCompose,
  waitForPptx,
} from '@/features/chat/pptxExport';
import { stageOfficeFile } from '@/open-genai/office/handoff';
import {
  useOfficeAvailable,
  useProcuretechGenerateAvailable,
} from '@/open-genai/optional-app-health/useOptionalAppAvailable';

type Props = {
  text: string;
  modelId?: string;
};

/** 回答と作り方の指示からスライドを作り、オフィスのスライド画面で開く。 */
export const ExportAnswerPowerPoint = ({ text, modelId }: Props) => {
  const officeAvailable = useOfficeAvailable();
  const generateAvailable = useProcuretechGenerateAvailable();
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState('');
  const [errorText, setErrorText] = useState('');
  const cancelRef = useRef(false);

  if (!officeAvailable || !generateAvailable || !text.trim()) {
    return null;
  }

  const close = () => {
    if (running) {
      cancelRef.current = true;
    }
    setIsOpen(false);
    setRunning(false);
    setErrorText('');
    setStep('');
  };

  const create = async () => {
    const prompt = instruction.trim();
    if (!prompt || running) return;
    cancelRef.current = false;
    setRunning(true);
    setErrorText('');
    setStep('原稿を整えています');
    try {
      const draft = await draftSlideMarkdown(text, prompt, modelId);
      if (cancelRef.current) return;
      if (!draft) {
        setErrorText('スライドの原稿を作れませんでした。指示を変えてもう一度試してください。');
        setRunning(false);
        return;
      }
      setStep('図を画像化しています');
      const deck = splitDeckTitle(draft);
      const prepared = await embedMermaidFences(deck.body);
      if (cancelRef.current) return;
      setStep('スライドを作っています');
      const jobId = await startPptxCompose(prepared.markdown, prepared.assets, deck.title, prompt);
      const bytes = await waitForPptx(jobId, setStep, () => cancelRef.current);
      if (cancelRef.current) return;
      await stageOfficeFile('回答.pptx', bytes);
      navigate('/office/powerpoint?local=1');
    } catch (error) {
      if (cancelRef.current) return;
      setErrorText(
        error instanceof Error && error.message ? error.message : 'スライドを作れませんでした。',
      );
      setRunning(false);
    }
  };

  return (
    <>
      <Button
        variant='text'
        type='button'
        size='sm'
        className='inline-flex items-center justify-center gap-x-1'
        aria-label='PowerPointに出力'
        onClick={() => {
          cancelRef.current = false;
          setErrorText('');
          setStep('');
          setIsOpen(true);
        }}
      >
        <PresentationIcon className='shrink-0' aria-hidden={true} />
        スライド
      </Button>
      <CustomDialog isOpen={isOpen} onClose={close}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={close}>
            PowerPointに出力
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170'>
              この回答をもとにスライドを作ります。枚数や聞き手など、作り方を書いてください。
            </p>
            <div className='mt-4 flex flex-col gap-1.5'>
              <Label htmlFor='pptx-instruction' size='sm'>
                スライドの作り方
              </Label>
              <Textarea
                id='pptx-instruction'
                rows={5}
                value={instruction}
                disabled={running}
                aria-disabled={running || undefined}
                placeholder='例: 庁内説明用に、5枚程度で要点を先に出す'
                onChange={(event) => setInstruction(event.target.value)}
              />
            </div>
            {running && (
              <ProgressIndicator className='mt-4' label={step || 'スライドを作っています'} />
            )}
            {errorText && <p className='mt-4 text-std-16N-170 text-error-1'>{errorText}</p>}
            <div className='mt-6 flex justify-end gap-2'>
              <Button variant='text' size='md' type='button' onClick={close}>
                キャンセル
              </Button>
              <Button
                variant='solid-fill'
                size='md'
                type='button'
                disabled={running || !instruction.trim()}
                aria-disabled={running || !instruction.trim() || undefined}
                onClick={() => void create()}
              >
                作成する
              </Button>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </>
  );
};
