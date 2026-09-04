import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError, teamApi } from '@/lib/fetcher';
import { type ProfileSchema, profileSchema } from '../schema';
import type { MyProfile } from '../types';

type Props = {
  profile: MyProfile;
  onUpdated: (profile: MyProfile) => void;
};

export const ProfileForm = ({ profile, onUpdated }: Props) => {
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ProfileSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(profileSchema),
    values: {
      lastName: profile.lastName,
      firstName: profile.firstName,
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      setError('');
      setDone(false);
      setIsLoading(true);
      const res = await teamApi.put<MyProfile>('my/profile', {
        lastName: data.lastName,
        firstName: data.firstName,
      });
      onUpdated(res.data);
      setDone(true);
    } catch (e) {
      if (isApiError(e)) {
        setError((e.data as { error?: string })?.error ?? '更新に失敗しました。');
      } else {
        setError('システムエラーが発生しました。ページをリロードして再度お試しください。');
      }
    } finally {
      setIsLoading(false);
    }
  });

  return (
    <form onSubmit={onSubmit} className='flex flex-col gap-4'>
      <div className='grid grid-cols-1 gap-4 sm:grid-cols-2'>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='settings-lastname' size='lg'>
            姓
          </Label>
          <Input
            id='settings-lastname'
            type='text'
            className='w-full'
            autoComplete='family-name'
            aria-describedby={errors.lastName ? 'settings-lastname-error' : undefined}
            {...register('lastName')}
          />
          {errors.lastName && (
            <ErrorText id='settings-lastname-error'>＊{errors.lastName.message}</ErrorText>
          )}
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='settings-firstname' size='lg'>
            名
          </Label>
          <Input
            id='settings-firstname'
            type='text'
            className='w-full'
            autoComplete='given-name'
            aria-describedby={errors.firstName ? 'settings-firstname-error' : undefined}
            {...register('firstName')}
          />
          {errors.firstName && (
            <ErrorText id='settings-firstname-error'>＊{errors.firstName.message}</ErrorText>
          )}
        </div>
      </div>

      {error && (
        <div className='rounded-6 bg-red-50 p-3 text-dns-14N-130 text-error-1'>{error}</div>
      )}
      {done && (
        <div className='rounded-6 bg-green-50 p-3 text-dns-14N-130 text-green-900'>
          プロフィールを更新しました。
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
          {isLoading ? '保存中' : '保存'}
        </LoadingButton>
      </div>
    </form>
  );
};
