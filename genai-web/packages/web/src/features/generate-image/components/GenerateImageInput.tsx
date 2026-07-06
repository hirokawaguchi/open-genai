import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { isSubmitKey } from '@/utils/keyboard';
import { type GenerateImageChatFormSchema, generateImageChatFormSchema } from '../schema';

type Props = {
  textareaId: string;
  content: string;
  loading?: boolean;
  onChangeContent: (content: string) => void;
  onSend: () => void;
};

export const GenerateImageInput = (props: Props) => {
  const { textareaId, content, onChangeContent, onSend } = props;

  const { usecase, chatId } = useUsecasePath();
  const { loading: chatLoading } = useChat(usecase, chatId);

  const loading = props.loading === undefined ? chatLoading : props.loading;

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<GenerateImageChatFormSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(generateImageChatFormSchema),
    values: {
      content,
    },
  });

  const onSubmit = handleSubmit((data) => {
    if (loading) return;
    onChangeContent(data.content);
    onSend();
  });

  return (
    <form className='w-full' aria-labelledby={`${textareaId}-heading`} onSubmit={onSubmit}>
      <h2 id={`${textareaId}-heading`} className='self-start my-1 text-std-16N-170'>
        生成したい画像の内容を入力してみましょう
      </h2>
      <div className='flex w-full flex-col gap-2'>
        <AutoResizeTextarea
          id={textareaId}
          className='resize-none'
          required
          aria-labelledby={`${textareaId}-heading`}
          aria-describedby={`${textareaId}-error`}
          onKeyDown={(e) => {
            if (isSubmitKey(e)) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          {...register('content', {
            onChange: (e) => {
              setValue('content', e.target.value);
              onChangeContent(e.target.value);
            },
          })}
        />
        {errors.content && (
          <ErrorText id={`${textareaId}-error`}>＊{errors.content.message}</ErrorText>
        )}

        <div className='flex w-full items-start justify-end'>
          <LoadingButton
            type='submit'
            variant='solid-fill'
            size='md'
            disabled={loading}
            onClick={() => {}}
            className='shrink-0 inline-flex justify-center items-center gap-1 min-w-36'
          >
            <SendIcon aria-hidden={true} className='shrink-0' />
            {loading ? '生成中...' : '送信'}
          </LoadingButton>
        </div>
      </div>
    </form>
  );
};
