import type React from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { plainFromRendered } from '@/components/latexToPlain';
import { Button } from '@/components/ui/dads/Button';
import { DocumentIcon } from '@/components/ui/icons/DocumentIcon';
import { answerDocx } from '@/open-genai/office/answerDocx';
import { stageOfficeFile } from '@/open-genai/office/handoff';
import { useOfficeAvailable } from '@/open-genai/optional-app-health/useOptionalAppAvailable';

type Props = {
  text: string;
  targetRef?: React.RefObject<HTMLElement | null>;
};

/** 表示中の回答を文書にして、オフィスの文書画面で開く。 */
export const ExportAnswerWord = ({ text, targetRef }: Props) => {
  const officeAvailable = useOfficeAvailable();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  if (!officeAvailable || !text.trim()) {
    return null;
  }

  const open = async () => {
    if (pending) return;
    setPending(true);
    try {
      const shown = targetRef?.current ? plainFromRendered(targetRef.current) : '';
      await stageOfficeFile('回答.docx', await answerDocx(shown || text.trim()));
      navigate('/office/word?local=1');
    } catch {
      setPending(false);
    }
  };

  return (
    <Button
      variant='text'
      type='button'
      size='sm'
      className='inline-flex items-center justify-center gap-x-1'
      aria-label={pending ? '開いています' : 'Wordに出力'}
      disabled={pending}
      onClick={() => void open()}
    >
      <DocumentIcon className='shrink-0' aria-hidden={true} />
      {pending ? '開いています' : 'Word'}
    </Button>
  );
};
