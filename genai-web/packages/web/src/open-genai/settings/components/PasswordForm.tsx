import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError, teamApi } from '@/lib/fetcher';
import { type PasswordSchema, passwordSchema } from '../schema';

export const PasswordForm = () => {
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PasswordSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(passwordSchema),
    defaultValues: {
      currentPassword: '',
      newPassword: '',
      confirmPassword: '',
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      setError('');
      setDone(false);
      setIsLoading(true);
      await teamApi.post('my/password', {
        currentPassword: data.currentPassword,
        newPassword: data.newPassword,
      });
      setDone(true);
      reset();
    } catch (e) {
      if (isApiError(e)) {
        setError((e.data as { error?: string })?.error ?? 'パスワードの変更に失敗しました。');
      } else {
        setError('システムエラーが発生しました。ページをリロードして再度お試しください。');
      }
    } finally {
      setIsLoading(false);
    }
  });

  return (
    <form onSubmit={onSubmit} className='flex flex-col gap-4'>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='settings-current-password' size='lg'>
          現在のパスワード<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id='settings-current-password'
          type='password'
          className='w-full max-w-md'
          autoComplete='current-password'
          aria-describedby={errors.currentPassword ? 'settings-current-password-error' : undefined}
          {...register('currentPassword')}
        />
        {errors.currentPassword && (
          <ErrorText id='settings-current-password-error'>
            ＊{errors.currentPassword.message}
          </ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='settings-new-password' size='lg'>
          新しいパスワード<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id='settings-new-password'
          type='password'
          className='w-full max-w-md'
          autoComplete='new-password'
          aria-describedby={errors.newPassword ? 'settings-new-password-error' : undefined}
          {...register('newPassword')}
        />
        {errors.newPassword ? (
          <ErrorText id='settings-new-password-error'>＊{errors.newPassword.message}</ErrorText>
        ) : (
          <p className='text-dns-14N-130 text-solid-gray-600'>8文字以上で入力してください。</p>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='settings-confirm-password' size='lg'>
          新しいパスワード（確認）<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id='settings-confirm-password'
          type='password'
          className='w-full max-w-md'
          autoComplete='new-password'
          aria-describedby={errors.confirmPassword ? 'settings-confirm-password-error' : undefined}
          {...register('confirmPassword')}
        />
        {errors.confirmPassword && (
          <ErrorText id='settings-confirm-password-error'>
            ＊{errors.confirmPassword.message}
          </ErrorText>
        )}
      </div>

      {error && (
        <div className='rounded-6 bg-red-50 p-3 text-dns-14N-130 text-error-1'>{error}</div>
      )}
      {done && (
        <div className='rounded-6 bg-green-50 p-3 text-dns-14N-130 text-green-900'>
          パスワードを変更しました。
        </div>
      )}

      <div className='flex justify-start'>
        <LoadingButton
          type='submit'
          variant='solid-fill'
          size='md'
          className='w-48'
          loading={isLoading}
        >
          {isLoading ? '変更中' : 'パスワードを変更'}
        </LoadingButton>
      </div>
    </form>
  );
};
