import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { SupportText } from '@/components/ui/dads/SupportText';
import { useGenerateTextStore } from '@/features/generate-text/stores/useGenerateTextStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { requestSubmitOnEnter, submitKeyHint } from '@/utils/keyboard';
import { GenerateTextFormSchema, generateTextFormSchema } from '../schema';

type Props = {
  setFollowing: (following: boolean) => void;
  getGeneratedText: (information: string, context: string) => void;
};

export const GenerateTextForm = (props: Props) => {
  const { setFollowing, getGeneratedText } = props;

  const { information, setInformation, context, setContext } = useGenerateTextStore();

  const { usecase, chatId } = useUsecasePath();
  const { loading } = useChat(usecase, chatId);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<GenerateTextFormSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(generateTextFormSchema),
    values: {
      information,
      format: context,
    },
  });

  const onSubmit = handleSubmit((data) => {
    setFollowing(true);
    setInformation(data.information);
    setContext(data.format ?? '');
    getGeneratedText(data.information, data.format ?? '');
  });

  return (
    <>
      <h2 className='sr-only'>文章生成フォーム</h2>
      <form onSubmit={onSubmit}>
        <div className='flex flex-col gap-3'>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='generate-text-original-input' size='lg'>
              文章の元になる情報<RequirementBadge>※必須</RequirementBadge>
            </Label>
            <SupportText id='generate-text-original-input-support'>
              生成したい文章の元となる情報を入力してください
            </SupportText>
            <AutoResizeTextarea
              id='generate-text-original-input'
              required
              rows={2}
              maxHeight={500}
              aria-describedby={`generate-text-original-input-support generate-text-submit-hint${errors.information ? ' generate-text-original-input-error' : ''}`}
              onKeyDown={requestSubmitOnEnter}
              {...register('information')}
            />
            {errors.information && (
              <ErrorText id='generate-text-original-input-error'>
                ＊{errors.information.message}
              </ErrorText>
            )}
          </div>

          <div className='flex flex-col gap-1.5'>
            <div className='flex flex-col items-start gap-2'>
              <Label htmlFor='generate-text-format-input' size='lg'>
                文章の形式
                <RequirementBadge isOptional>※任意</RequirementBadge>
              </Label>
            </div>
            <SupportText id='generate-text-format-input-support'>
              例：マークダウン、ブログ、ビジネスメールなど
            </SupportText>
            <AutoResizeTextarea
              id='generate-text-format-input'
              aria-describedby={`generate-text-format-input-support generate-text-submit-hint${errors.format ? ' generate-text-format-input-error' : ''}`}
              onKeyDown={requestSubmitOnEnter}
              {...register('format')}
            />
            {errors.format && (
              <ErrorText id='generate-text-format-input-error'>＊{errors.format.message}</ErrorText>
            )}
          </div>
        </div>

        <SupportText id='generate-text-submit-hint' className='mt-4 text-center'>
          {submitKeyHint}
        </SupportText>

        <div className='mt-3 flex justify-center'>
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
