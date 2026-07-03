import { ExApp } from 'genai-web';
import { PiBookOpenBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ExAppUsageMarkdownRenderer } from './ExAppUsageMarkdownRenderer';

type Props = {
  exApp: ExApp;
};

export const ExAppHeader = (props: Props) => {
  const { exApp } = props;

  return (
    <div className='mb-6 flex flex-col gap-4'>
      <BreadcrumbsNav
        items={[
          { label: 'ホーム', to: '/' },
          { label: 'AIアプリ', to: '/apps' },
          { label: exApp.exAppName },
        ]}
      />
      <div className='flex items-baseline gap-1'>
        <h1 className='mb-2 flex justify-start text-std-20B-160 lg:text-std-24B-150'>
          {exApp?.exAppName}
        </h1>
      </div>
      {exApp?.description && (
        <p className='text-std-16N-170 text-solid-gray-700'>{exApp.description}</p>
      )}
      {exApp?.howToUse && (
        <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
          <DisclosureSummary>
            <span className='flex items-center text-std-16B-150'>
              <PiBookOpenBold className='mr-2 size-5 flex-none' />
              使い方（クリックで開閉）
            </span>
          </DisclosureSummary>
          <div className='mt-3'>
            <ExAppUsageMarkdownRenderer content={exApp.howToUse} size='sm' />
          </div>
        </Disclosure>
      )}
    </div>
  );
};
