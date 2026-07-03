import { PiBookOpenBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';

export const TranscribeHeader = () => {
  return (
    <div className='mb-6 flex flex-col gap-4'>
      <BreadcrumbsNav
        items={[
          { label: 'ホーム', to: '/' },
          { label: 'AIアプリ', to: '/apps' },
          { label: '音声ファイルから文字起こし' },
        ]}
      />
      <h1 className='mb-2 flex justify-start text-std-20B-160 lg:text-std-24B-150'>
        音声ファイルから文字起こし
      </h1>
      <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
        <DisclosureSummary>
          <span className='flex items-center text-std-16B-150'>
            <PiBookOpenBold className='mr-2 size-5 flex-none' />
            使い方（クリックで開閉）
          </span>
        </DisclosureSummary>
        <div className='prose prose-sm mt-3 max-w-full'>
          <h2>想定用途</h2>
        <p>音声ファイルから文字起こしすることができます。</p>
        <h3>アプリ個別の留意点</h3>
        <p>
          大きなファイルを入力する場合は処理が著しく重くなる場合がありますので、その場合はファイルを分割して入力してください。なお、生成された文字起こしの正確性は利用者で確認してください。
        </p>
        <h3>入力例</h3>
        <p>文字起こししたい音声ファイルを入力してください。</p>
        <h2>操作方法</h2>
        <p>
          文字起こししたい音声ファイルを入力します。話者認識をオンにすることで、話者を識別して文字起こしをすることもできます。
        </p>
        <Disclosure className='my-4'>
          <DisclosureSummary>仕組み</DisclosureSummary>
          <div className='pl-7'>
            <p>
              音声認識エンジンで音声ファイルを文字起こしします。特別な文書は読み込ませていません。音声はクラウドには送信されません。
            </p>
          </div>
        </Disclosure>
        </div>
      </Disclosure>
    </div>
  );
};
