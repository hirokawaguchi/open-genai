import { useMemo } from 'react';
import type { PinnedAppItem } from '@/open-genai/app-pins/types';
import { useImageAvailable } from '@/open-genai/image-health/useImageAvailable';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';

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
      to: '/transcribe',
      description: '音声ファイルから文字起こし',
    });

    return items;
  }, [imageAvailable]);
};

export const ALL_APPS_NAV_ITEM: NavLinkItem = {
  label: 'すべてのAIアプリ',
  to: '/apps',
};

export const pinnedAppHref = (item: PinnedAppItem): string =>
  item.app.isDefault ? `/${item.app.value}` : `/apps/${item.teamIdKey}/${item.app.value}`;
