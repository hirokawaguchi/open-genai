import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { SupportText } from '@/components/ui/dads/SupportText';
import { useTranslateStore } from '@/features/translate/stores/useTranslateStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { TranslateFormSchema, translateFormSchema } from '../schema';
import { TranslatedResult } from './TranslatedResult';

type Props = {
  typingTextOutput: string;
  translatedSentence: string;
  getTranslation: (sentence: string, language: string, context: string) => void;
};

export const TranslateForm = (props: Props) => {
  const { typingTextOutput, translatedSentence, getTranslation } = props;

  const { sentence, setSentence, additionalContext, setAdditionalContext, language } =
    useTranslateStore();

  const { usecase, chatId } = useUsecasePath();
  const { loading } = useChat(usecase, chatId);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TranslateFormSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(translateFormSchema),
    values: {
      sentence,
      additionalContext,
    },
  });

  const onSubmit = handleSubmit((data) => {
    setSentence(data.sentence);
    setAdditionalContext(data.additionalContext ?? '');
    getTranslation(data.sentence, language, data.additionalContext ?? '');
  });

  return (
    <>
      <h2 className='sr-only'>翻訳フォーム</h2>
      <form onSubmit={onSubmit}>
        <div className='mt-4 flex w-full flex-col gap-2 lg:flex-row'>
          <div className='w-full lg:w-1/2'>
            <div className='relative flex flex-col'>
              <div className='relative'>
                <div className='mb-3 flex flex-col gap-1.5'>
                  <Label htmlFor='translate-original-input' size='lg'>
                    翻訳したい文章<RequirementBadge>※必須</RequirementBadge>
                  </Label>
                  <SupportText id='translate-original-input-support'>
                    言語は自動検出されます
                  </SupportText>
                  <AutoResizeTextarea
                    className='pb-9'
                    required
                    id='translate-original-input'
                    rows={5}
                    maxHeight={-1}
                    aria-describedby={`translate-original-input-support${errors.sentence ? ' translate-original-input-error' : ''}`}
                    {...register('sentence', {
                      onChange: (e) => setSentence(e.target.value),
                    })}
                  />
                  {errors.sentence && (
                    <ErrorText id='translate-original-input-error'>
                      ＊{errors.sentence.message}
                    </ErrorText>
                  )}
                </div>
              </div>
            </div>
          </div>

          <TranslatedResult
            typingTextOutput={typingTextOutput}
            translatedSentence={translatedSentence}
          />
        </div>

        <div className='flex flex-col gap-1.5'>
          <div className='flex flex-col items-start gap-2'>
            <Label htmlFor='translate-additional-context-input' size='lg'>
              追加コンテキスト
              <RequirementBadge isOptional>※任意</RequirementBadge>
            </Label>
          </div>
          <SupportText id='translate-additional-context-input-support'>
            追加で考慮してほしい点を入力することができます（カジュアルさ等）
          </SupportText>
          <AutoResizeTextarea
            id='translate-additional-context-input'
            aria-describedby={`translate-additional-context-input-support${errors.additionalContext ? ' translate-additional-context-input-error' : ''}`}
            {...register('additionalContext')}
          />
          {errors.additionalContext && (
            <ErrorText id='translate-additional-context-input-error'>
              {errors.additionalContext.message}
            </ErrorText>
          )}
        </div>

        <div className='mt-6 flex justify-center'>
          <Button
            type='submit'
            variant='solid-fill'
            size='lg'
            className='w-60'
            aria-disabled={loading}
          >
            {loading ? '実行中...' : '実行'}
          </Button>
        </div>
      </form>
    </>
  );
};
