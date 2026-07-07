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
import { PinnedAppsSection } from '@/open-genai/app-pins/PinnedAppsSection';
import { useImageAvailable } from '@/open-genai/image-health/useImageAvailable';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';
import { LandingForm } from './components/LandingForm';

export const LandingPage = () => {
  const imageAvailable = useImageAvailable();
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
              <>
                <li>
                  <Card
                    title='チャット'
                    className='h-full'
                    to='/chat'
                    description='着想や整理のための壁打ち'
                  />
                </li>
                {isUseCaseEnabled('generate') && (
                  <li>
                    <Card
                      title='文章を生成'
                      className='h-full'
                      to='/generate'
                      description='手元の情報をもとに文章を作成'
                    />
                  </li>
                )}
                {isUseCaseEnabled('translate') && (
                  <li>
                    <Card
                      title='翻訳'
                      className='h-full'
                      to='/translate'
                      description='手元の文章を他の言語に翻訳'
                    />
                  </li>
                )}
                {isUseCaseEnabled('image') && imageAvailable && (
                  <li>
                    <Card
                      title='画像を生成'
                      className='h-full'
                      to='/image'
                      description='プロンプトから資料用の挿絵やイメージ案を作成'
                    />
                  </li>
                )}
                {isUseCaseEnabled('diagram') && (
                  <li>
                    <Card
                      title='ダイアグラムを生成'
                      className='h-full'
                      to='/diagram'
                      description='テキストからフローチャートやマインドマップを作成'
                    />
                  </li>
                )}
              </>
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
