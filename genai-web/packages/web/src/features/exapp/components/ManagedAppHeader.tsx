import type { ReactNode } from 'react';
import { PiBookOpenBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { useFetchExApp } from '@/features/exapp/hooks/useFetchExApp';
import { ExAppHeader } from './ExAppHeader';
import { ExAppUsageMarkdownRenderer } from './ExAppUsageMarkdownRenderer';

type Crumb = { label: string; to?: string };

type Props = {
  teamId: string;
  exAppId: string;
  fallbackTitle: string;
  fallbackDescription?: string;
  fallbackHowTo?: ReactNode;
  breadcrumbItems?: Crumb[];
  /** false のとき DB を読まずフォールバックだけ出す（庁外ゲスト画面など） */
  enabled?: boolean;
  children?: ReactNode;
};

/**
 * 専用ページ用ヘッダ。共通／管理者アプリ編集の紹介・使い方をそのまま表示する。
 * 取得前・未登録時は fallback を使う。
 */
export const ManagedAppHeader = (props: Props) => {
  const {
    teamId,
    exAppId,
    fallbackTitle,
    fallbackDescription,
    fallbackHowTo,
    breadcrumbItems,
    enabled = true,
    children,
  } = props;
  const { data: exApp } = useFetchExApp(enabled ? teamId : '', enabled ? exAppId : '');

  if (exApp && !breadcrumbItems && !children) {
    return <ExAppHeader exApp={exApp} />;
  }

  const title = (exApp?.exAppName || '').trim() || fallbackTitle;
  const description = (exApp?.description || '').trim() || fallbackDescription;
  const howTo = (exApp?.howToUse || '').trim();
  const crumbs = breadcrumbItems ?? [
    { label: 'ホーム', to: '/' },
    { label: 'AIアプリ', to: '/apps' },
    { label: title },
  ];

  return (
    <div className='flex flex-col gap-4'>
      {crumbs.length > 0 && <BreadcrumbsNav items={crumbs} />}
      <h1 className='text-std-20B-160 lg:text-std-24B-150'>{title}</h1>
      {children}
      {description && (
        <p className='text-std-16N-170 text-solid-gray-700'>{description}</p>
      )}
      {howTo ? (
        <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
          <DisclosureSummary>
            <span className='flex items-center text-std-16B-150'>
              <PiBookOpenBold className='mr-2 size-5 flex-none' />
              使い方（クリックで開閉）
            </span>
          </DisclosureSummary>
          <div className='mt-3'>
            <ExAppUsageMarkdownRenderer content={howTo} size='sm' />
          </div>
        </Disclosure>
      ) : fallbackHowTo ? (
        <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
          <DisclosureSummary>
            <span className='flex items-center text-std-16B-150'>
              <PiBookOpenBold className='mr-2 size-5 flex-none' />
              使い方（クリックで開閉）
            </span>
          </DisclosureSummary>
          <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
            {fallbackHowTo}
          </div>
        </Disclosure>
      ) : null}
    </div>
  );
};
