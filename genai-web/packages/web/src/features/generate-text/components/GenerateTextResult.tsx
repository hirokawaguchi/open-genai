import { Ref, useRef } from 'react';
import { Markdown } from '@/components/Markdown';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';

type Props = {
  scrollableContainer: Ref<HTMLDivElement>;
  typingTextOutput: string;
  text: string;
};

export const GenerateTextResult = (props: Props) => {
  const { scrollableContainer, typingTextOutput, text } = props;

  const copyTextRef = useRef<HTMLDivElement>(null);

  const { usecase, chatId } = useUsecasePath();
  const { loading, continueGeneration, getStopReason } = useChat(usecase, chatId);

  const stopReason = getStopReason();
  const isInitial = !loading && text === '';
  const showResult = !loading && text !== '';

  return (
    <div
      ref={scrollableContainer}
      className='relative mt-5 rounded-8 border border-solid-gray-420 p-4'
    >
      <h2 className='sr-only'>生成された文章</h2>

      {isInitial && (
        <div className='leading-175 text-solid-gray-536'>生成された文章がここに表示されます</div>
      )}

      <div ref={copyTextRef}>
        <Markdown>{typingTextOutput}</Markdown>
      </div>

      {loading && <ProgressIndicator className='my-0.5' />}

      {stopReason === 'max_tokens' && (
        <div className='mt-4'>
          <Button variant='outline' size='md' onClick={() => continueGeneration()}>
            続きを出力
          </Button>
        </div>
      )}

      {showResult && (
        <div className='-mb-2 flex w-full justify-end'>
          <ButtonCopy text={text} targetRef={copyTextRef} />
        </div>
      )}
    </div>
  );
};
