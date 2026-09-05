import { zodResolver } from '@hookform/resolvers/zod';
import { TeamUser } from 'genai-web';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
import { Checkbox } from '@/components/ui/dads/Checkbox';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { StatusBadge } from '@/components/ui/dads/StatusBadge';
import { SupportText } from '@/components/ui/dads/SupportText';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError } from '@/lib/fetcher';
import { focus } from '@/utils/focus';
import { useUpdateTeamMember } from '../hooks/useUpdateTeamMember';
import { TeamMemberUpdateSchema, teamMemberUpdateSchema } from '../schema';

type Props = {
  member: TeamUser;
};

export const TeamMemberEditForm = (props: Props) => {
  const navigate = useNavigate();

  const { member } = props;
  const { updateTeamMember, mutateTeamMembers } = useUpdateTeamMember();
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const { register, handleSubmit } = useForm<TeamMemberUpdateSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(teamMemberUpdateSchema),
    values: {
      email: member.username,
      isAdmin: member.isAdmin,
      isPrimary: member.isPrimary ?? false,
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      setError('');
      setIsLoading(true);
      await updateTeamMember(member.teamId, member.userId, {
        isAdmin: data.isAdmin,
        isPrimary: data.isPrimary,
      });
      await mutateTeamMembers();
      navigate(`/teams/${member.teamId}/members`);
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
        <Label htmlFor={`team-member-edit-email-input`} size='lg'>
          メールアドレス
          <StatusBadge>編集不可</StatusBadge>
        </Label>
        <SupportText id={`team-member-edit-email-input-support`}>
          ユーザーのメールアドレスは編集できません
        </SupportText>
        <Input
          id={`team-member-edit-email-input`}
          type='text'
          required
          className='w-full'
          data-autofocus
          aria-describedby={`team-member-edit-email-input-support`}
          readOnly
          {...register('email')}
        />
      </div>

      <Checkbox {...register('isAdmin')}>チーム管理者に設定する</Checkbox>
      <Checkbox {...register('isPrimary')}>このチームを主所属にする</Checkbox>

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
          onClick={onSubmit}
          loading={isLoading}
        >
          {isLoading ? '更新中' : '更新'}
        </LoadingButton>
      </div>
    </form>
  );
};
