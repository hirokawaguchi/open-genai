import { Suspense, useEffect, useMemo } from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import { useLocation, useParams } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import { Divider } from '@/components/ui/dads/Divider';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { ErrorFallback } from '@/components/ui/ErrorFallback';
import { APP_TITLE } from '@/constants';
import { ExAppChat } from '@/features/exapp/components/ExAppChat';
import { ExAppForm } from '@/features/exapp/components/ExAppForm';
import { ExAppHeader } from '@/features/exapp/components/ExAppHeader';
import { ExAppInvokedHistories } from '@/features/exapp/components/ExAppInvokedHistories';
import { ExAppResult } from '@/features/exapp/components/ExAppResult';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { LayoutBody } from '@/layout/LayoutBody';
import { isJSON } from '@/utils/isJSON';
import { ExAppInvokedHistoriesLoading } from './components/ExAppInvokedHistoriesLoading';
import { useFetchExApp } from './hooks/useFetchExApp';
import { useFetchExAppSchema } from './hooks/useFetchExAppSchema';
import { useExAppInvokeStore } from './stores/useExAppInvokeStore';
import { GovAIFormDefaultValue } from './types';

export const ExAppPage = () => {
  const { exAppResponse, requestLoading, error, clear } = useExAppInvokeStore();

  const { pathname } = useLocation();

  const params = useParams<{ teamId?: string; exAppId?: string }>();
  const teamId = params.teamId ?? '';
  const exAppId = params.exAppId ?? '';
  const {
    data: exApp,
    isLoading: isExAppLoading,
    error: exAppFetchError,
  } = useFetchExApp(teamId, exAppId);

  useEffect(() => {
    clear();
  }, [pathname, clear]);

  const placeholderUiJson = useMemo(() => {
    return exApp && isJSON(exApp.placeholder) ? JSON.parse(exApp.placeholder) : {};
  }, [exApp]);

  const configObj = useMemo(() => {
    if (!exApp?.config || !isJSON(exApp.config)) {
      return {} as Record<string, unknown>;
    }
    try {
      return (JSON.parse(exApp.config) ?? {}) as Record<string, unknown>;
    } catch {
      return {} as Record<string, unknown>;
    }
  }, [exApp]);

  // 設定(config)の dify_app_type が "chat" のアプリは対話型 UI で開く
  const isChatApp = configObj?.dify_app_type === 'chat';

  const placeholderEmpty = useMemo(
    () => Object.keys(placeholderUiJson ?? {}).length === 0,
    [placeholderUiJson],
  );

  // 非chat かつ placeholder 未設定の Dify アプリは、実行時に /schema からフォーム生成
  const shouldFetchSchema =
    !!exApp && !isChatApp && placeholderEmpty && !!configObj?.dify_base_url;

  const { uiJson: fetchedUiJson, isLoading: isSchemaLoading } = useFetchExAppSchema(
    teamId,
    exAppId,
    shouldFetchSchema,
  );

  const uiJson = shouldFetchSchema ? fetchedUiJson : placeholderUiJson;

  const defaultValuesJson = useMemo(() => {
    if (!uiJson) {
      return {};
    }

    const defaultValues: GovAIFormDefaultValue = {};
    for (const key of Object.keys(uiJson)) {
      if (uiJson[key]?.['default_value'] !== undefined) {
        defaultValues[key] = uiJson[key]['default_value'];
      }
    }
    return defaultValues;
  }, [uiJson]);

  const exAppName = exApp?.exAppName ?? 'GovAI';
  const { liveStatusMessage } = useLiveStatusMessage({
    active: true,
    loading: requestLoading,
    messages: {
      loading: `${exAppName}が回答を生成しています...`,
      loadingContinue: `${exAppName}が引き続き回答を生成しています...`,
      completed: exAppResponse?.outputs
        ? `${exAppName}の回答：${exAppResponse.outputs}`
        : `${exAppName}の回答がありません。`,
      error: error ? `${exAppName}のエラー：${error}` : undefined,
    },
  });

  const pageTitle = exApp?.exAppName
    ? `${exApp.exAppName}${APP_TITLE ? ` | ${APP_TITLE}` : ''}`
    : undefined;

  return (
    <LayoutBody>
      <PageTitle title={pageTitle} />
      <div className='mx-auto p-6 max-w-(--page-width) lg:p-8'>
        <div>
          {isExAppLoading && <ProgressIndicator label='AIアプリを読み込み中...' />}

          {exAppFetchError && <ErrorText>{exAppFetchError}</ErrorText>}

          {!isExAppLoading && exApp && (
            <>
              <ExAppHeader exApp={exApp} />
              <Divider className='my-6' />

              {isChatApp ? (
                <ExAppChat exApp={exApp} />
              ) : (
                <>
                  {shouldFetchSchema && isSchemaLoading ? (
                    <ProgressIndicator label='入力フォームを読み込み中...' />
                  ) : (
                    <ExAppForm
                      exApp={exApp}
                      uiJson={uiJson}
                      defaultValues={defaultValuesJson}
                    />
                  )}
                  <Divider className='my-6' />

                  <ExAppResult
                    shouldShowConversationHistory={exApp.placeholder.includes(
                      'conversation_history',
                    )}
                  />

                  <Divider className='my-6' />

                  <div className='mb-3'>
                    <h2 className='my-4 text-std-18B-160'>利用履歴</h2>
                    <ErrorBoundary resetKeys={[exApp.exAppId]} fallbackRender={ErrorFallback}>
                      <Suspense fallback={<ExAppInvokedHistoriesLoading />}>
                        <ExAppInvokedHistories exApp={exApp} />
                      </Suspense>
                    </ErrorBoundary>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <div aria-live='assertive' aria-atomic='true' className='sr-only'>
          {liveStatusMessage}
        </div>
      </div>
    </LayoutBody>
  );
};
