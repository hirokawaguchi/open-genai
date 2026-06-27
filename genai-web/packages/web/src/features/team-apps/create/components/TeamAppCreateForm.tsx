import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router';
import { Checkbox } from '@/components/ui/dads/Checkbox';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Divider } from '@/components/ui/dads/Divider';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Legend } from '@/components/ui/dads/Legend';
import { Link } from '@/components/ui/dads/Link';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Textarea } from '@/components/ui/dads/Textarea';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { EXAPP_STATUS_OPTIONS, MARKDOWN_EXAMPLE } from '@/constants';
import { isApiError } from '@/lib/fetcher';
import { escapeNewlinesInJsonFields } from '@/utils/escapeNewlinesInJsonFields';
import { focus } from '@/utils/focus';
import { useCreateTeamApp } from '../hooks/useCreateTeamApp';
import { teamAppCreateSchema } from '../schema';

export const TeamAppCreateForm = () => {
  const navigate = useNavigate();
  const { teamId } = useParams();

  const { createTeamApp, mutateTeamApps } = useCreateTeamApp();
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(teamAppCreateSchema),
    mode: 'onSubmit',
    defaultValues: {
      systemPromptKeyName: 'systemPrompt',
      config: `{
    "max_payload_size": "6MB"
}`,
      status: '',
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      setError('');
      setIsLoading(true);
      await createTeamApp(teamId ?? '', {
        exAppName: data.name,
        endpoint: data.endpoint,
        config: data.config,
        placeholder: escapeNewlinesInJsonFields(data.uiFormat, ['default_value', 'desc']),
        systemPrompt: data.systemPrompt,
        systemPromptKeyName: data.systemPromptKeyName,
        description: data.description,
        howToUse: data.howToUse,
        apiKey: data.apiKey,
        copyable: data.copyable,
        status: data.status,
      });
      await mutateTeamApps();
      navigate(`/teams/${teamId}/apps`);
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
        <Label htmlFor={`team-app-name`} size='lg'>
          名前<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id={`team-app-name`}
          type='text'
          required
          data-autofocus
          className='w-full'
          aria-describedby={errors.name ? `team-app-name-error` : undefined}
          {...register('name')}
        />
        {errors.name && <ErrorText id={`team-app-name-error`}>＊{errors.name.message}</ErrorText>}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-description`} size='lg'>
          概要
          <RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-app-description-support`}>
          一覧に表示する簡単な説明（30文字程度）
        </SupportText>
        <Input
          id={`team-app-description`}
          type='text'
          required
          aria-describedby={errors.description ? `team-app-description-error` : undefined}
          {...register('description')}
        />
        {errors.description && (
          <ErrorText id={`team-app-description-error`}>＊{errors.description.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-how-to-use`} size='lg'>
          使い方
          <RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-app-how-to-use-support`}>
          想定用途・入力例・仕組みなど。マークダウン記法を使用できます
        </SupportText>
        <Textarea
          id={`team-app-how-to-use`}
          required
          aria-describedby={
            errors.howToUse
              ? `team-app-how-to-use-support team-app-how-to-use-error`
              : `team-app-how-to-use-support`
          }
          rows={3}
          {...register('howToUse')}
        />
        {errors.howToUse && (
          <ErrorText id={`team-app-how-to-use-error`}>＊{errors.howToUse.message}</ErrorText>
        )}
        <Disclosure>
          <DisclosureSummary>マークダウン記法の入力例</DisclosureSummary>
          <div className='mt-2'>
            <pre className='border border-transparent bg-solid-gray-50 p-3 text-dns-14N-130 leading-140 wrap-break-word whitespace-pre-wrap'>
              {MARKDOWN_EXAMPLE}
            </pre>
          </div>
        </Disclosure>
      </div>

      <Divider className='my-6' />

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-endpoint-url`} size='lg'>
          APIエンドポイントのURL<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id={`team-app-endpoint-url`}
          type='url'
          required
          className='w-full'
          aria-describedby={errors.endpoint ? `team-app-endpoint-url-error` : undefined}
          {...register('endpoint')}
        />
        {errors.endpoint && (
          <ErrorText id={`team-app-endpoint-url-error`}>＊{errors.endpoint.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-api-key`} size='lg'>
          APIキー<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id={`team-app-api-key`}
          type='text'
          required
          className='w-full'
          aria-describedby={errors.apiKey ? `team-app-api-key-error` : undefined}
          {...register('apiKey')}
        />
        {errors.apiKey && (
          <ErrorText id={`team-app-api-key-error`}>＊{errors.apiKey.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-request-data`} size='lg'>
          APIリクエストのデータ形式(JSON)
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-request-data-support`}>
          JSON形式で入力してください。フォーム入力が必要なアプリで定義します。対話型（Dify チャット）や入力不要のアプリでは空で構いません。
          <Link href='/docs/api-request-data-format' target='_blank'>
            APIリクエストのデータ形式解説
          </Link>
        </SupportText>
        <Textarea
          id={`team-app-request-data`}
          className='field-sizing-content min-h-[calc(3lh+2rem+2px)]'
          aria-describedby={
            errors.uiFormat
              ? `team-app-request-data-support team-app-request-data-error`
              : `team-app-request-data-support`
          }
          {...register('uiFormat')}
        />
        {errors.uiFormat && (
          <ErrorText id={`team-app-request-data-error`}>＊{errors.uiFormat.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-config`} size='lg'>
          コンフィグ（JSON）
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-config-support`}>JSON形式で入力してください</SupportText>
        <Textarea
          id={`team-app-config`}
          className='field-sizing-content min-h-[calc(3lh+2rem+2px)]'
          aria-describedby={
            errors.config
              ? `team-app-config-support team-app-config-error`
              : `team-app-config-support`
          }
          {...register('config')}
        />
        {errors.config && (
          <ErrorText id={`team-app-config-error`}>＊{errors.config.message}</ErrorText>
        )}
      </div>

      <Divider className='my-6' />

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-system-prompt`} size='lg'>
          システムプロンプト
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <Textarea
          id={`team-app-system-prompt`}
          className='field-sizing-content min-h-[calc(3lh+2rem+2px)]'
          aria-describedby={errors.systemPrompt ? `team-app-system-prompt-error` : undefined}
          {...register('systemPrompt')}
        />
        {errors.systemPrompt && (
          <ErrorText id={`team-app-system-prompt-error`}>＊{errors.systemPrompt.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-system-prompt-key`} size='lg'>
          システムプロンプトのキー名
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-system-prompt-key-support`}>
          ペイロード送信時のキー名を入力してください
        </SupportText>
        <Input
          id={`team-app-system-prompt-key`}
          aria-describedby={
            errors.systemPromptKeyName
              ? `team-app-system-prompt-key-support team-app-system-prompt-key-error`
              : `team-app-system-prompt-key-support`
          }
          {...register('systemPromptKeyName')}
        />
        {errors.systemPromptKeyName && (
          <ErrorText id={`team-app-system-prompt-key-error`}>
            ＊{errors.systemPromptKeyName.message}
          </ErrorText>
        )}
      </div>

      <Divider className='my-6' />

      <div className='flex flex-col items-start gap-1.5'>
        <Label htmlFor={`team-app-status`} size='lg'>
          公開ステータス
          <RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-app-status-support`}>
          下書きの場合、一覧には表示されません
        </SupportText>
        <Select
          id={`team-app-status`}
          className='min-w-60'
          aria-describedby={
            errors.status
              ? `team-app-status-support team-app-status-error`
              : `team-app-status-support`
          }
          {...register('status')}
        >
          <option value=''>選択してください</option>
          {EXAPP_STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        {errors.status && (
          <ErrorText id={`team-app-status-error`}>＊{errors.status.message}</ErrorText>
        )}
      </div>

      <Divider className='my-6' />

      <fieldset>
        <Legend className='mb-1.5' size='lg'>
          その他の設定
        </Legend>
        <Checkbox {...register('copyable')}>このAIアプリをコピー可能にする</Checkbox>
      </fieldset>

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
