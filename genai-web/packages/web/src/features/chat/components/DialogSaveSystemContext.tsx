import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useId, useState } from 'react';
import { useForm } from 'react-hook-form';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { SupportText } from '@/components/ui/dads/SupportText';
import { SystemContextSaveSchema, systemContextSaveSchema } from '../schema';
import type { MyTeam, SystemContextShareOptions } from '../hooks/useSystemContextApi';
import { useSystemContextApi } from '../hooks/useSystemContextApi';

type Props = {
  className?: string;
  systemContext: string;
  isOpen: boolean;
  onSave: (title: string, systemContext: string, options?: SystemContextShareOptions) => void;
  onClose: () => void;
};

export const DialogSaveSystemContext = (props: Props) => {
  const { systemContext, isOpen, onSave, onClose } = props;
  const formId = useId();

  const { listMyTeams } = useSystemContextApi();
  const [isPublic, setIsPublic] = useState(false);
  const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
  const [myTeams, setMyTeams] = useState<MyTeam[]>([]);

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
  } = useForm<SystemContextSaveSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(systemContextSaveSchema),
  });

  // モーダルダイアログが開いたときに現在のシステムプロンプトを設定
  useEffect(() => {
    if (isOpen) {
      reset({
        title: '',
        systemContext,
      });
      setIsPublic(false);
      setSelectedTeamIds([]);
      listMyTeams()
        .then(setMyTeams)
        .catch(() => setMyTeams([]));
    }
    // listMyTeams は毎回新規参照だが、isOpen 変化時のみ実行する
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, systemContext, reset]);

  const toggleTeam = (teamId: string) => {
    setSelectedTeamIds((prev) =>
      prev.includes(teamId) ? prev.filter((id) => id !== teamId) : [...prev, teamId],
    );
  };

  const onSubmit = handleSubmit((data) => {
    onSave(data.title, data.systemContext, { isPublic, sharedTeams: selectedTeamIds });
    reset();
    setIsPublic(false);
    setSelectedTeamIds([]);
    onClose();
  });

  return (
    <CustomDialog isOpen={isOpen} onClose={onClose}>
      <CustomDialogPanel>
        <CustomDialogHeader>システムプロンプトの保存</CustomDialogHeader>
        <CustomDialogBody>
          <p className='mb-3'>保存することで、プロンプト一覧から選択して使えるようになります</p>
          <form className='flex flex-col gap-3' onSubmit={onSubmit}>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor={`${formId}-prompt-name-input`} size='lg'>
                タイトル<RequirementBadge>※必須</RequirementBadge>
              </Label>
              <Input
                id={`${formId}-prompt-name-input`}
                type='text'
                required
                className='w-full'
                aria-describedby={errors.title ? `${formId}-prompt-name-input-error` : undefined}
                {...register('title')}
              />
              {errors.title && (
                <ErrorText id={`${formId}-prompt-name-input-error`}>
                  ＊{errors.title.message}
                </ErrorText>
              )}
            </div>

            <div className='flex flex-col gap-1.5'>
              <Label htmlFor={`${formId}-prompt-content-input`} size='lg'>
                システムプロンプト<RequirementBadge>※必須</RequirementBadge>
              </Label>
              <AutoResizeTextarea
                id={`${formId}-prompt-content-input`}
                required
                rows={2}
                maxHeight={500}
                aria-describedby={
                  errors.systemContext ? `${formId}-prompt-content-input-error` : undefined
                }
                {...register('systemContext')}
              />
              {errors.systemContext && (
                <ErrorText id={`${formId}-prompt-content-input-error`}>
                  ＊{errors.systemContext.message}
                </ErrorText>
              )}
            </div>

            <div className='flex flex-col gap-1.5'>
              <Label htmlFor={`${formId}-public`} size='lg'>
                共有範囲
              </Label>
              <label htmlFor={`${formId}-public`} className='flex items-center gap-2'>
                <input
                  id={`${formId}-public`}
                  type='checkbox'
                  checked={isPublic}
                  onChange={(e) => setIsPublic(e.target.checked)}
                />
                <span>全体公開（全利用者が使えるようにする）</span>
              </label>
              {myTeams.length > 0 && (
                <fieldset className='flex flex-col gap-1'>
                  <legend className='text-dns-14N-130 text-solid-gray-600'>
                    チームで共有（所属チームから選択）
                  </legend>
                  {myTeams.map((team) => (
                    <label key={team.teamId} className='flex items-center gap-2'>
                      <input
                        type='checkbox'
                        checked={selectedTeamIds.includes(team.teamId)}
                        onChange={() => toggleTeam(team.teamId)}
                      />
                      <span>{team.teamName}</span>
                    </label>
                  ))}
                </fieldset>
              )}
              <SupportText className='whitespace-pre-wrap'>
                {myTeams.length === 0
                  ? 'チーム共有を使うには、いずれかのチームに所属している必要があります。'
                  : ''}
                {'未指定なら自分のみが使えます。'}
              </SupportText>
            </div>

            <div className='mt-4 flex flex-row-reverse justify-between gap-2'>
              <Button type='submit' variant='solid-fill' size='md'>
                保存して閉じる
              </Button>
              <Button variant='text' size='md' onClick={() => onClose()}>
                キャンセル
              </Button>
            </div>
          </form>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
