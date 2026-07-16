import { zodResolver } from '@hookform/resolvers/zod';
import type { ExApp } from 'genai-web';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
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
import { useCopyTeamApp } from '../hooks/useCopyTeamApp';
import { teamAppCopySchema } from '../schema';

type Props = {
  app: ExApp;
};

export const TeamAppCopyForm = (props: Props) => {
  const { app } = props;

  const navigate = useNavigate();

  const { copyTeamApp, mutateTeamApps } = useCopyTeamApp();
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({
    mode: 'onSubmit',
    resolver: zodResolver(teamAppCopySchema),
    values: {
      name: app.exAppName,
      endpoint: app.endpoint,
      config: app.config ?? '',
      uiFormat: app.placeholder.replace(/\\n/g, '\r\n') ?? '',
      systemPrompt: app.systemPrompt ?? '',
      systemPromptKeyName: app.systemPromptKeyName ?? '',
      description: app.description,
      howToUse: app.howToUse ?? '',
      apiKey: undefined,
      copyable: app.copyable ?? false,
      status: '',
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    try {
      setError('');
      setIsLoading(true);
      await copyTeamApp(app.teamId, app.exAppId, {
        exAppName: data.name,
        endpoint: data.endpoint,
        config: data.config,
        placeholder: escapeNewlinesInJsonFields(data.uiFormat, ['default_value', 'desc']),
        systemPrompt: data.systemPrompt,
        systemPromptKeyName: data.systemPromptKeyName,
        description: data.description,
        howToUse: data.howToUse,
        apiKey: data.apiKey || undefined,
        copyable: data.copyable,
        status: data.status,
      });
      await mutateTeamApps();
      navigate(`/teams/${app.teamId}/apps`);
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
        <Label htmlFor={`team-app-copy-name`} size='lg'>
          名前<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id={`team-app-copy-name`}
          type='text'
          required
          data-autofocus
          className='w-full'
          aria-describedby={errors.name ? `team-app-copy-name-error` : undefined}
          {...register('name')}
        />
        {errors.name && (
          <ErrorText id={`team-app-copy-name-error`}>＊{errors.name.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-description`} size='lg'>
          概要
          <RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-description-support`}>
          一覧に表示する簡単な説明（30文字程度）
        </SupportText>
        <Input
          id={`team-app-copy-description`}
          type='text'
          required
          aria-describedby={errors.description ? `team-app-copy-description-error` : undefined}
          {...register('description')}
        />
        {errors.description && (
          <ErrorText id={`team-app-copy-description-error`}>
            ＊{errors.description.message}
          </ErrorText>
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

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-how-to-use`} size='lg'>
          使い方
          <RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-how-to-use-support`}>
          想定用途・入力例・仕組みなど。マークダウン記法を使用できます
        </SupportText>
        <Textarea
          id={`team-app-copy-how-to-use`}
          required
          aria-describedby={
            errors.howToUse
              ? `team-app-copy-how-to-use-support team-app-copy-how-to-use-error`
              : `team-app-copy-how-to-use-support`
          }
          rows={3}
          {...register('howToUse')}
        />
        {errors.howToUse && (
          <ErrorText id={`team-app-copy-how-to-use-error`}>＊{errors.howToUse.message}</ErrorText>
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
        <Label htmlFor={`team-app-copy-endpoint-url`} size='lg'>
          APIエンドポイントのURL<RequirementBadge>※必須</RequirementBadge>
        </Label>
        <Input
          id={`team-app-copy-endpoint-url`}
          type='url'
          required
          className='w-full'
          aria-describedby={errors.endpoint ? `team-app-copy-endpoint-url-error` : undefined}
          {...register('endpoint')}
        />
        {errors.endpoint && (
          <ErrorText id={`team-app-copy-endpoint-url-error`}>＊{errors.endpoint.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-api-key`} size='lg'>
          APIキー<RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-api-key-support`}>
          未入力の場合はコピー元のAPIキーを使用します
        </SupportText>
        <Input
          id={`team-app-copy-api-key`}
          type='text'
          className='w-full'
          aria-describedby={
            errors.apiKey
              ? `team-app-copy-api-key-support team-app-copy-api-key-error`
              : `team-app-copy-api-key-support`
          }
          {...register('apiKey')}
        />
        {errors.apiKey && (
          <ErrorText id={`team-app-copy-api-key-error`}>＊{errors.apiKey.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-request-data`} size='lg'>
          APIリクエストのデータ形式(JSON)
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-request-data-support`}>
          JSON形式で入力してください。フォーム入力が必要なアプリで定義します。対話型（Dify チャット）や入力不要のアプリでは空で構いません。
          <Link href='/docs/api-request-data-format' target='_blank'>
            APIリクエストのデータ形式解説
          </Link>
        </SupportText>
        <Textarea
          id={`team-app-copy-request-data`}
          className='field-sizing-content min-h-[calc(3lh+2rem+2px)]'
          aria-describedby={
            errors.uiFormat
              ? `team-app-copy-request-data-support team-app-copy-request-data-error`
              : `team-app-copy-request-data-support`
          }
          {...register('uiFormat')}
        />
        {errors.uiFormat && (
          <ErrorText id={`team-app-copy-request-data-error`}>＊{errors.uiFormat.message}</ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-config`} size='lg'>
          コンフィグ（JSON）
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-config-support`}>JSON形式で入力してください</SupportText>
        <Textarea
          id={`team-app-copy-config`}
          className='field-sizing-content min-h-[calc(3lh+2rem+2px)]'
          aria-describedby={
            errors.config
              ? `team-app-copy-config-support team-app-copy-config-error`
              : `team-app-copy-config-support`
          }
          {...register('config')}
        />
        {errors.config && (
          <ErrorText id={`team-app-copy-config-error`}>＊{errors.config.message}</ErrorText>
        )}
      </div>

      <Divider className='my-6' />

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-system-prompt`} size='lg'>
          システムプロンプト
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <Textarea
          id={`team-app-copy-system-prompt`}
          className='field-sizing-content min-h-[calc(3lh+2rem+2px)]'
          aria-describedby={errors.systemPrompt ? `team-app-copy-system-prompt-error` : undefined}
          {...register('systemPrompt')}
        />
        {errors.systemPrompt && (
          <ErrorText id={`team-app-copy-system-prompt-error`}>
            ＊{errors.systemPrompt.message}
          </ErrorText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor={`team-app-copy-system-prompt-key`} size='lg'>
          システムプロンプトのキー名
          <RequirementBadge isOptional>※任意</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-system-prompt-key-support`}>
          ペイロード送信時のキー名を入力してください
        </SupportText>
        <Input
          id={`team-app-copy-system-prompt-key`}
          aria-describedby={
            errors.systemPromptKeyName
              ? `team-app-copy-system-prompt-key-support team-app-copy-system-prompt-key-error`
              : `team-app-copy-system-prompt-key-support`
          }
          {...register('systemPromptKeyName')}
        />
        {errors.systemPromptKeyName && (
          <ErrorText id={`team-app-copy-system-prompt-key-error`}>
            ＊{errors.systemPromptKeyName.message}
          </ErrorText>
        )}
      </div>

      <Divider className='my-6' />

      <div className='flex flex-col items-start gap-1.5'>
        <Label htmlFor={`team-app-copy-status`} size='lg'>
          公開ステータス
          <RequirementBadge>※必須</RequirementBadge>
        </Label>
        <SupportText id={`team-app-copy-status-support`}>
          下書きの場合、一覧には表示されません
        </SupportText>
        <Select
          id={`team-app-copy-status`}
          className='min-w-60'
          aria-describedby={
            errors.status
              ? `team-app-copy-status-support team-app-copy-status-error`
              : `team-app-copy-status-support`
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
          <ErrorText id={`team-app-copy-status-error`}>＊{errors.status.message}</ErrorText>
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
          {isLoading ? '作成中' : 'コピーして作成'}
        </LoadingButton>
      </div>
    </form>
  );
};
