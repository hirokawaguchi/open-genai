import { useMemo } from 'react';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import type { PinnedAppItem } from '@/open-genai/app-pins/types';
import { useImageAvailable } from '@/open-genai/image-health/useImageAvailable';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';

/** Open GENAI の文字起こしは Amazon Transcribe ではなく Whisper exApp */
export const WHISPER_EXAPP_PATH = `/apps/${COMMON_EXAPPS_TEAM_ID}/whisper`;

/** ナレッジ管理 専用ページ。タグ/登録/管理の各 exApp を集約する。 */
export const KNOWLEDGE_PATH = '/knowledge';

/** ナレッジ管理 専用ページへ集約する（＝リダイレクトする）旧 exApp ID。検索(rag)は除く。 */
export const KNOWLEDGE_EXAPP_IDS = new Set(['rag-tags', 'rag-register', 'rag-maintain']);

/** プロンプトテンプレートは汎用 exApp フォームではなく専用ページで提供する */
export const PROMPT_TEMPLATES_PATH = '/prompts';

/** プロンプトテンプレート exApp の識別子（専用ページへ振り替える対象） */
export const PROMPT_EXAPP_ID = 'prompt';

/** 日程調整は汎用 exApp フォームではなく専用ページで提供する */
export const CHOSEI_PATH = '/chosei';

/** 日程調整 exApp の識別子（専用ページへ振り替える対象） */
export const CHOSEI_EXAPP_ID = 'chosei';

/** 書類領域分割チェックは汎用 exApp フォームではなく専用ページで提供する */
export const DOCCHECK_PATH = '/doccheck';

/** 書類読取とチェック exApp の識別子（専用ページへ振り替える対象） */
export const DOCCHECK_EXAPP_ID = 'doccheck';

/** 監査ログは管理者限定の専用ページで提供する */
export const AUDIT_ADMIN_PATH = '/admin/audit';

/** 監査ログ exApp の識別子（専用ページへ振り替える対象） */
export const AUDIT_EXAPP_ID = 'audit';

/** 利用者一括管理は管理者限定の専用ページで提供する */
export const USERMGMT_ADMIN_PATH = '/admin/users';

/** 利用者一括管理 exApp の識別子（専用ページへ振り替える対象） */
export const USERMGMT_EXAPP_ID = 'usermgmt';

/** モデル利用制御は管理者限定の専用ページで提供する */
export const MODELPOLICY_ADMIN_PATH = '/admin/model-policy';

/** モデル利用制御 exApp の識別子（専用ページへ振り替える対象） */
export const MODELPOLICY_EXAPP_ID = 'modelpolicy';

/** 入力制限（禁止ワード）は管理者限定の専用ページで提供する */
export const NGWORD_ADMIN_PATH = '/admin/ngword';

/** 入力制限 exApp の識別子（専用ページへ振り替える対象） */
export const NGWORD_EXAPP_ID = 'ngword';

export type NavLinkItem = {
  label: string;
  to: string;
  /** チャット新規開始など */
  state?: Record<string, unknown>;
  description?: string;
};

/** おすすめ（組み込みユースケース）リンク。画像は health を見て出し分け。 */
export const useRecommendedNavItems = (): NavLinkItem[] => {
  const imageAvailable = useImageAvailable();

  return useMemo(() => {
    const items: NavLinkItem[] = [
      {
        label: 'チャット',
        to: '/chat',
        state: { shouldReset: true },
        description: '着想や整理のための壁打ち',
      },
    ];

    if (isUseCaseEnabled('generate')) {
      items.push({
        label: '文章を生成',
        to: '/generate',
        description: '手元の情報をもとに文章を作成',
      });
    }
    if (isUseCaseEnabled('translate')) {
      items.push({
        label: '翻訳',
        to: '/translate',
        description: '手元の文章を他の言語に翻訳',
      });
    }
    if (isUseCaseEnabled('image') && imageAvailable) {
      items.push({
        label: '画像を生成',
        to: '/image',
        description: 'プロンプトから資料用の挿絵やイメージ案を作成',
      });
    }
    if (isUseCaseEnabled('diagram')) {
      items.push({
        label: 'ダイアグラムを生成',
        to: '/diagram',
        description: 'テキストからフローチャートやマインドマップを作成',
      });
    }

    items.push({
      label: '文字起こし',
      to: WHISPER_EXAPP_PATH,
      description: '音声ファイルから文字起こし',
    });

    items.push({
      label: 'プロンプトテンプレート',
      to: PROMPT_TEMPLATES_PATH,
      description: '標準／共有テンプレートを選んでチャットへ',
    });

    items.push({
      label: '日程調整',
      to: CHOSEI_PATH,
      description: '庁内・外部向けの日程調整（要 profile chosei）',
    });

    items.push({
      label: '書類読取とチェック',
      to: DOCCHECK_PATH,
      description: '領域分割 OCR と分散チェック（要 profile doccheck）',
    });

    items.push({
      label: 'ナレッジ管理',
      to: KNOWLEDGE_PATH,
      description: '共有・所属チームの資料を登録／管理（検索は「ナレッジ検索」）',
    });

    return items;
  }, [imageAvailable]);
};

export const ALL_APPS_NAV_ITEM: NavLinkItem = {
  label: 'すべてのAIアプリ',
  to: '/apps',
};

export const pinnedAppHref = (item: PinnedAppItem): string => {
  // タグ管理/ドキュメント登録/ドキュメント管理の各 exApp は専用ページへ集約
  if (!item.app.isDefault && KNOWLEDGE_EXAPP_IDS.has(item.app.value)) {
    return KNOWLEDGE_PATH;
  }
  // プロンプトテンプレートは専用ページへ振り替える（汎用 exApp URL を使わない）
  if (item.app.value === PROMPT_EXAPP_ID) {
    return PROMPT_TEMPLATES_PATH;
  }
  // 日程調整は専用ページへ振り替える
  if (item.app.value === CHOSEI_EXAPP_ID) {
    return CHOSEI_PATH;
  }
  // 書類読取とチェックは専用ページへ振り替える
  if (item.app.value === DOCCHECK_EXAPP_ID) {
    return DOCCHECK_PATH;
  }
  // 監査ログは管理者限定の専用ページへ振り替える
  if (item.app.value === AUDIT_EXAPP_ID) {
    return AUDIT_ADMIN_PATH;
  }
  // 利用者一括管理も管理者限定の専用ページへ振り替える
  if (item.app.value === USERMGMT_EXAPP_ID) {
    return USERMGMT_ADMIN_PATH;
  }
  // モデル利用制御も管理者限定の専用ページへ振り替える
  if (item.app.value === MODELPOLICY_EXAPP_ID) {
    return MODELPOLICY_ADMIN_PATH;
  }
  // 入力制限（禁止ワード）も管理者限定の専用ページへ振り替える
  if (item.app.value === NGWORD_EXAPP_ID) {
    return NGWORD_ADMIN_PATH;
  }
  return item.app.isDefault ? `/${item.app.value}` : `/apps/${item.teamIdKey}/${item.app.value}`;
};
