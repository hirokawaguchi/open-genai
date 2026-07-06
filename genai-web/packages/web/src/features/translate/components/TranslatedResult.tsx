import { useRef } from 'react';
import { Markdown } from '@/components/Markdown';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { CustomSelect } from '@/components/ui/CustomSelect';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { useTranslateStore } from '@/features/translate/stores/useTranslateStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { LANGUAGES } from '../constants';

type Props = {
  typingTextOutput: string;
  translatedSentence: string;
};

export const TranslatedResult = (props: Props) => {
  const { typingTextOutput, translatedSentence } = props;

  const { language, setLanguage } = useTranslateStore();

  const { usecase, chatId } = useUsecasePath();
  const { loading, continueGeneration, getStopReason } = useChat(usecase, chatId);

  const copyTextRef = useRef<HTMLDivElement>(null);

  const isInitial = !loading && translatedSentence === '';
  const showResult = !loading && translatedSentence !== '';
  const stopReason = getStopReason();

  return (
    <div className='flex w-full flex-col gap-1 lg:w-1/2'>
      <h3 className='sr-only'>翻訳結果</h3>

      <div className='flex flex-none items-end lg:h-16'>
        <CustomSelect
          label='翻訳する言語：'
          labelClassName='text-dns-14B-120'
          value={language}
          className='mb-1'
          options={LANGUAGES.map((l) => {
            return { value: l, label: l };
          })}
          onChange={setLanguage}
        />
      </div>

      <div className='mb-3 flex flex-1 flex-col rounded-8 border border-solid-gray-420 p-4'>
        {isInitial && (
          <div className='leading-175 text-solid-gray-536'>翻訳結果がここに表示されます</div>
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
          <div className='mt-auto -mb-2 flex w-full justify-end gap-1'>
            <ButtonCopy text={translatedSentence} targetRef={copyTextRef} />
          </div>
        )}
      </div>
    </div>
  );
};
