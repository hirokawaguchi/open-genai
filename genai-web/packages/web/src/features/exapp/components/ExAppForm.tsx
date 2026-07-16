import { ExApp, InvokeExAppHistory } from 'genai-web';
import { useEffect, useMemo, useState } from 'react';
import { FieldValues, useForm } from 'react-hook-form';
import { useSWRConfig } from 'swr';
import { unstable_serialize } from 'swr/infinite';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { SupportText } from '@/components/ui/dads/SupportText';
import { isJSON } from '@/utils/isJSON';
import { submitKeyHint } from '@/utils/keyboard';
import { useExAppInvokeState } from '../hooks/useExAppInvokeState';
import { getExAppHistoriesKey } from '../hooks/useFetchInvokedExAppHistories';
import { useResolveExAppSchema } from '../hooks/useResolveExAppSchema';
import { ConversationHistory, GovAIFormDefaultValue, GovAIFormUI, GovAIFormUIJson } from '../types';
import { getConfirmMessage } from '../utils/formSpec';
import { buildPayload } from '../utils/buildPayload';
import { formatConversationHistory } from '../utils/formatConversationHistory';
import { formatFileInfo } from '../utils/formatFileInfo';
import { processFormFiles } from '../utils/processFormFiles';
import { transformFormData } from '../utils/transformFormData';
import { validatePayloadSize } from '../utils/validatePayloadSize';
import { ExAppFormComponentBuilder } from './ExAppFormComponentBuilder';
import { SystemPrompt } from './SystemPrompt';

type Props = {
  exApp: ExApp;
  uiJson: GovAIFormUIJson;
  defaultValues: GovAIFormDefaultValue;
};

export const ExAppForm = (props: Props) => {
  const { exApp, uiJson, defaultValues } = props;

  const {
    requestLoading,
    setRequestLoading,
    setError: setInvokeError,
    setExAppResponse,
    invokeRequest,
  } = useExAppInvokeState();
  const { mutate: mutateHistories } = useSWRConfig();

  const [validationError, setValidationError] = useState('');

  const systemPromptKey =
    exApp.systemPromptKeyName && exApp.systemPromptKeyName.length > 0
      ? exApp.systemPromptKeyName
      : 'system_prompt';

  const formValues = exApp.systemPrompt
    ? { ...defaultValues, [systemPromptKey]: exApp.systemPrompt }
    : defaultValues;

  const {
    register,
    handleSubmit,
    setValue,
    trigger,
    clearErrors,
    watch,
    getValues,
    formState: { errors, submitCount },
  } = useForm({
    mode: 'onSubmit',
    defaultValues: formValues,
    values: formValues,
    // OpenGENAI Form Spec v1: visibleWhen で非表示になったフィールドは登録解除し、
    // 送信対象・バリデーション対象から外す（新キー未使用の静的フォームには影響なし）。
    shouldUnregister: true,
  });

  // OpenGENAI Form Spec v1: リアクティブ解決で差し替わるフォーム定義。
  const [liveUiJson, setLiveUiJson] = useState<GovAIFormUIJson>(uiJson);
  useEffect(() => {
    setLiveUiJson(uiJson);
  }, [uiJson]);

  const { resolve } = useResolveExAppSchema(exApp.teamId, exApp.exAppId);

  const watchedValues = watch();

  // スキーマの default_value。select 等は初期レンダリング時に RHF 値が未確定でも
  // ネイティブ要素は先頭/既定候補を表示するため、visibleWhen/preview 判定が実表示と
  // ずれる。既定値をフォールバック合成して初期表示から正しく評価する。
  const schemaDefaults = useMemo(() => {
    const d: Record<string, string> = {};
    for (const k of Object.keys(liveUiJson)) {
      const dv = (liveUiJson[k] as GovAIFormUI | undefined)?.default_value;
      if (dv !== undefined) {
        d[k] = dv;
      }
    }
    return d;
  }, [liveUiJson]);

  // visibleWhen / preview の評価に使う現在値（未確定キーは default_value で補完）。
  const effectiveValues = useMemo(() => {
    const defined = Object.fromEntries(
      Object.entries(watchedValues).filter(([, v]) => v !== undefined),
    );
    return { ...schemaDefaults, ...defined };
  }, [watchedValues, schemaDefaults]);

  // 動的スキーマの default_value は UI に見えても RHF 登録前だと未設定になり、
  // 必須チェックに引っかかる。スキーマ取得後にフォーム状態へ同期する。
  useEffect(() => {
    for (const [key, val] of Object.entries(schemaDefaults)) {
      const current = getValues(key);
      if (current === undefined || current === '') {
        setValue(key, val, { shouldValidate: false, shouldDirty: false });
      }
    }
  }, [schemaDefaults, setValue, getValues]);

  // reactive 指定のフィールド群（変更時に /resolve を呼ぶトリガ）。
  const reactiveKeys = useMemo(
    () =>
      Object.keys(liveUiJson).filter(
        (k) => (liveUiJson[k] as GovAIFormUI | undefined)?.reactive === true,
      ),
    [liveUiJson],
  );
  const reactiveSignature = reactiveKeys
    .map((k) => `${k}=${effectiveValues?.[k] ?? ''}`)
    .join('&');

  useEffect(() => {
    if (reactiveKeys.length === 0) {
      return;
    }
    let cancelled = false;
    const handle = setTimeout(async () => {
      const current = getValues();
      const payload: Record<string, unknown> = { ...schemaDefaults };
      for (const [k, v] of Object.entries(current)) {
        if (v !== undefined) {
          payload[k] = v;
        }
      }
      const next = await resolve(payload);
      if (!cancelled && next && Object.keys(next).length > 0) {
        setLiveUiJson(next);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
    // reactive フィールドの値が変わった時だけ再解決する。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reactiveSignature, reactiveKeys.length]);

  const [invokeHistory, setInvokeHistory] = useState<InvokeExAppHistory | null>(null);
  const [conversationHistory, setConversationHistory] = useState('');

  useEffect(() => {
    const history = localStorage.getItem('history');
    if (!history) {
      return;
    }
    try {
      const parsedHistory = JSON.parse(history);
      setInvokeHistory(parsedHistory);

      const historyInputs = `
${parsedHistory.inputs['conversation_histories'] ? formatConversationHistory(parsedHistory.inputs['conversation_histories'] as ConversationHistory[]) + '\n ## 入力' : '## 入力'}

${Object.keys(parsedHistory.inputs)
  .filter((key) => key !== 'conversation_histories')
  .map(
    (key) =>
      key +
      ': ' +
      (key === 'files' ? formatFileInfo(parsedHistory.inputs[key]) : parsedHistory.inputs[key]),
  )
  .join('\n')}

## 出力

${parsedHistory.outputs}

---

                `;

      setConversationHistory(historyInputs);
    } catch (e) {
      console.error(e);
    }

    localStorage.removeItem('history');
  }, []);

  // 不可逆操作の確認ダイアログ（OpenGENAI Form Spec v1: item.confirm）
  const [pendingData, setPendingData] = useState<FieldValues | null>(null);
  const [confirmMessage, setConfirmMessage] = useState('');

  // 送信ゲート: 選択内容に confirm が必要ならダイアログを挟み、確定後に実行する。
  const onSubmit = (data: FieldValues) => {
    if (requestLoading) {
      return;
    }
    const message = getConfirmMessage(liveUiJson, effectiveValues);
    if (message) {
      setPendingData(data);
      setConfirmMessage(message);
      return;
    }
    void performInvoke(data);
  };

  const performInvoke = async (data: FieldValues) => {
    if (requestLoading) {
      return;
    }

    const transformedData = transformFormData(data, liveUiJson);

    const files = await processFormFiles(data);

    if (exApp.config) {
      const config = isJSON(exApp.config) ? JSON.parse(exApp.config) : {};
      if (
        config.max_payload_size &&
        !validatePayloadSize(config.max_payload_size, transformedData, files)
      ) {
        setValidationError(
          `アップロード可能なデータの合計サイズは${config.max_payload_size}までです。テキスト量やファイル数を見直してください。また、ファイルサイズについてはBase64エンコードされた後のサイズで計算されるため元のサイズより1.4倍大きくなります。`,
        );
        return;
      }
    }

    const payload = buildPayload({
      data: transformedData,
      files,
      invokeHistory,
      systemPromptKey: exApp.systemPromptKeyName,
    });

    try {
      setRequestLoading(true);
      setInvokeError(null);
      setExAppResponse(null);
      setValidationError('');

      await invokeRequest({
        teamId: exApp.teamId,
        exAppId: exApp.exAppId,
        inputs: payload,
        sessionId: invokeHistory?.sessionId ?? crypto.randomUUID(),
      });
    } catch (error: unknown) {
      if (error instanceof Error) {
        setInvokeError(error);
      }
    } finally {
      setRequestLoading(false);
      mutateHistories(unstable_serialize(getExAppHistoriesKey(exApp.teamId, exApp.exAppId)));
    }
  };

  return (
    <>
      <h2 className='sr-only'>AIアプリ入力フォーム</h2>
      <form className='flex flex-col gap-8' onSubmit={handleSubmit(onSubmit)}>
        <ExAppFormComponentBuilder
          uiJson={liveUiJson}
          register={register}
          setValue={setValue}
          trigger={trigger}
          clearErrors={clearErrors}
          errors={errors}
          submitCount={submitCount}
          values={effectiveValues}
        />

        {exApp.systemPrompt && (
          <div className='flex flex-col gap-4'>
            <SystemPrompt exApp={exApp} register={register} errors={errors} />
          </div>
        )}

        {conversationHistory && (
          <div className='flex flex-col gap-4'>
            <Disclosure>
              <DisclosureSummary>会話履歴</DisclosureSummary>
              <pre className='mt-2 border border-transparent bg-solid-gray-50 px-3 text-dns-14N-130 leading-140 wrap-break-word whitespace-pre-wrap'>
                {conversationHistory}
              </pre>
            </Disclosure>
          </div>
        )}

        {validationError && <ErrorText>＊{validationError}</ErrorText>}

        <div className='flex flex-col items-center gap-3'>
          <SupportText id='exapp-submit-hint'>{submitKeyHint}</SupportText>
          <Button
            aria-disabled={requestLoading ? true : undefined}
            variant='solid-fill'
            size='lg'
            className='w-60'
            type='submit'
          >
            {requestLoading ? '実行中...' : '実行'}
          </Button>
        </div>
      </form>

      <CustomDialog
        isOpen={pendingData !== null}
        onClose={() => {
          setPendingData(null);
          setConfirmMessage('');
        }}
      >
        <CustomDialogPanel>
          <CustomDialogHeader>実行の確認</CustomDialogHeader>
          <CustomDialogBody>
            <p className='mb-4 whitespace-pre-wrap'>{confirmMessage}</p>
            <div className='flex flex-row-reverse justify-between gap-2'>
              <Button
                variant='solid-fill'
                size='md'
                onClick={() => {
                  const data = pendingData;
                  setPendingData(null);
                  setConfirmMessage('');
                  if (data) {
                    void performInvoke(data);
                  }
                }}
              >
                実行する
              </Button>
              <Button
                variant='text'
                size='md'
                onClick={() => {
                  setPendingData(null);
                  setConfirmMessage('');
                }}
              >
                キャンセル
              </Button>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </>
  );
};
