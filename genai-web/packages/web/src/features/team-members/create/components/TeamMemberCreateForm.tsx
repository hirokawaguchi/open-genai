import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router';
import { Checkbox } from '@/components/ui/dads/Checkbox';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { SupportText } from '@/components/ui/dads/SupportText';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError } from '@/lib/fetcher';
import { focus } from '@/utils/focus';
import { useCreateTeamMember } from '../hooks/useCreateTeamMember';
import { TeamMemberCreateSchema, teamMemberCreateSchema } from '../schema';

export const TeamMemberCreateForm = () => {
  const navigate = useNavigate();

  const { teamId } = useParams();
  const { createTeamMember, mutateTeamMembers } = useCreateTeamMember();
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TeamMemberCreateSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(teamMemberCreateSchema),
    defaultValues: { isAdmin: false, isPrimary: false },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      setError('');
      setIsLoading(true);
      await createTeamMember(teamId ?? '', {
        email: data.email,
        isAdmin: data.isAdmin,
        isPrimary: data.isPrimary,
      });
      await mutateTeamMembers();
      navigate(`/teams/${teamId ?? ''}/members`);
    } catch (e) {
      if (isApiError(e)) {
        setError((e.data as { error?: string })?.error ?? '');
      } else {
        setError('システムエラーが発生しました。ページをリロードして再度お試しください。');
      }
      focus('server-error');
    } finally {
      setIsLoading(false);
    }
  });

  return (
    <form onSubmit={onSubmit} className='flex flex-col gap-3 my-4'>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-member-email-input`} size='lg'>
          メールアドレス<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-member-email-input-support`}>
          追加するユーザーのメールアドレスを入力してください
        </SupportText>
        <Input
          id={`team-member-email-input`}
          type='text'
          required
          className='w-full'
          data-autofocus
          aria-describedby={
            errors.email
              ? `team-member-email-input-support team-member-email-input-error`
              : `team-member-email-input-support`
          }
          {...register('email')}
        />
        {errors.email && (
          <ErrorText id={`team-member-email-input-error`}>＊{errors.email.message}</ErrorText>
        )}
      </div>

      <Checkbox {...register('isAdmin')}>チーム管理者に設定する</Checkbox>
      <Checkbox {...register('isPrimary')}>このチームを主所属にする</Checkbox>
      <SupportText>
        主所属は1つだけです。親チームに所属している人は、配下チームを自動で閲覧できます。
      </SupportText>

      {error && (
        <section className='my-4'>
          <h2 id='server-error' className='sr-only' tabIndex={-1}>
            システムエラー
          </h2>
          <div
            className={`mx-auto flex w-full flex-col gap-2 rounded-6 bg-red-50 p-4 text-center text-error-1`}
          >
            <p>{error}</p>
          </div>
        </section>
      )}

      <div className='mt-4 flex justify-center gap-2'>
        <LoadingButton
          type='submit'
          variant='solid-fill'
          size='lg'
          className='w-60'
          loading={isLoading}
        >
          {isLoading ? '作成中' : '作成'}
        </LoadingButton>
      </div>
    </form>
  );
};
