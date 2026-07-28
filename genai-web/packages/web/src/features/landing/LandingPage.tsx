import { Suspense } from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import { Link } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { APP_TITLE } from '@/constants';
import { Card } from '@/features/landing/components/Card';
import { TOP_CHAT_SYSTEM_PROMPT } from '@/features/landing/constants';
import { RecommendedGovAI } from '@/features/landing/types';
import { LayoutBody } from '@/layout/LayoutBody';
import { useRecommendedNavItems } from '@/layout/navItems';
import { PinnedAppsSection } from '@/open-genai/app-pins/PinnedAppsSection';
import { LandingForm } from './components/LandingForm';

export const LandingPage = () => {
  const recommendedNavItems = useRecommendedNavItems();
  // 各環境のGovAIの情報を取得
  const recommendedGovAI: RecommendedGovAI[] = (() => {
    try {
      const data = import.meta.env.VITE_APP_GOVAIS_FOR_HOMEPAGE;
      return typeof data === 'string' ? JSON.parse(data) : [];
    } catch (error) {
      console.error('Failed to parse recommended GovAI data', error);
      return [];
    }
  })();

  return (
    <LayoutBody>
      <PageTitle title={APP_TITLE ? `${APP_TITLE} :` : 'トップページ'} />
      <div className='mx-auto px-6 max-w-(--page-width) lg:px-8 pb-24'>
        {TOP_CHAT_SYSTEM_PROMPT && <LandingForm />}

        <ErrorBoundary fallbackRender={() => null}>
          <Suspense fallback={null}>
            <PinnedAppsSection />
          </Suspense>
        </ErrorBoundary>

        <div className='mt-8 lg:mt-10'>
          <h2 className='mb-6 flex justify-start text-std-24B-150'>おすすめアプリ</h2>
          <ul className='grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-4'>
            {recommendedGovAI && recommendedGovAI.length > 0 ? (
              recommendedGovAI.map((govAI) => (
                <li key={govAI.exAppId}>
                  <Card
                    title={govAI.title}
                    className='h-full'
                    to={`/apps/${govAI.teamId}/${govAI.exAppId}`}
                    description={govAI.description}
                  />
                </li>
              ))
            ) : (
              recommendedNavItems.map((item) => (
                <li key={item.to}>
                  <Card
                    title={item.label}
                    className='h-full'
                    to={item.to}
                    description={item.description ?? ''}
                  />
                </li>
              ))
            )}
          </ul>
        </div>
        <div className='mt-8 flex justify-center'>
          <Button className='inline-flex items-center px-8!' variant='solid-fill' size='lg' asChild>
            <Link to='/apps'>すべてのAIアプリを見る</Link>
          </Button>
        </div>
      </div>
    </LayoutBody>
  );
};
