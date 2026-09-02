/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 画面に出すサービス名称（ヘッダー・フッター・ブラウザタブ） */
  readonly VITE_APP_TITLE: string;
  readonly VITE_APP_ENV: string;
  readonly VITE_APP_API_ENDPOINT: string;
  readonly VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT: string;
  readonly VITE_APP_REGION: string;
  readonly VITE_APP_USER_POOL_ID: string;
  readonly VITE_APP_USER_POOL_CLIENT_ID: string;
  readonly VITE_APP_IDENTITY_POOL_ID: string;
  readonly VITE_APP_PREDICT_STREAM_FUNCTION_ARN: string;
  readonly VITE_APP_SELF_SIGN_UP_ENABLED: string;
  readonly VITE_APP_VERSION: string;
  readonly VITE_APP_MODEL_REGION: string;
  readonly VITE_APP_MODEL_IDS: string;
  readonly VITE_APP_IMAGE_MODEL_IDS: string;
  readonly VITE_APP_ENDPOINT_NAMES: string;
  readonly VITE_APP_SAMLAUTH_ENABLED: string;
  readonly VITE_APP_SAML_COGNITO_DOMAIN_NAME: string;
  readonly VITE_APP_SAML_COGNITO_FEDERATED_IDENTITY_PRIMARY_PROVIDER_NAME: string;
  readonly VITE_APP_SAML_COGNITO_FEDERATED_IDENTITY_ADDITIONAL_PROVIDER_NAMES: string;
  readonly VITE_APP_HIDDEN_USE_CASES: string;
  readonly VITE_APP_GOVAIS_FOR_HOMEPAGE: string;
  readonly VITE_APP_TOP_CHAT_SYSTEM_PROMPT: string;
  readonly VITE_APP_TOP_CHAT_SYSTEM_PROMPT_TITLE: string;
  /** ナビ配置: header（既定）| sidebar */
  readonly VITE_APP_NAV_LAYOUT: string;
  /** 画像生成の初期ステップ数（既定 50。FastSD/LCM 向けは 4 など） */
  readonly VITE_APP_IMAGE_DEFAULT_STEP: string;
  /** 画像生成の初期 CFG スケール（既定 7。FastSD/LCM 向けは 1 など） */
  readonly VITE_APP_IMAGE_DEFAULT_CFG: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
