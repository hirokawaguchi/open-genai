import { PiBookOpenBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ModelSelector } from './ModelSelector';

export const DiagramHeader = () => {
  return (
    <div className='mb-6 flex flex-col gap-4'>
      <BreadcrumbsNav
        items={[
          { label: 'ホーム', to: '/' },
          { label: 'AIアプリ', to: '/apps' },
          { label: 'ダイアグラムを生成' },
        ]}
      />
      <h1 className='flex justify-start text-std-20B-160 lg:text-std-24B-150'>
        ダイアグラムを生成
      </h1>
      <ModelSelector />
      <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
        <DisclosureSummary>
          <span className='flex items-center text-std-16B-150'>
            <PiBookOpenBold className='mr-2 size-5 flex-none' />
            使い方（クリックで開閉）
          </span>
        </DisclosureSummary>
        <div className='prose prose-sm mt-3 max-w-full'>
          <h2>想定用途</h2>
        <p>
          文章を元に、フローチャート/円グラフ/マインドマップなどのダイアグラムの生成をすることができます。
        </p>
        <h3>アプリ個別の留意点</h3>
        <p>
          長文を入力する場合は処理が著しく重くなる場合がありますので、その場合は入力テキストの内容を単純化するなど工夫してください。なお、生成されたチャート等の正確性は利用者で確認してください。
        </p>
        <h3>入力例</h3>
        <p>図にしたい任意の文章を入力してください。</p>
        <h2>操作方法</h2>
        <p>
          図にしたい任意の文章を入力します。AIを選択すると、生成AIが適切な図を選択し、生成します。AIモデルのプルダウンより利用するAIモデルを選択してください。利用するAIモデルによって、結果が変わることがあります。
        </p>
        <Disclosure className='my-4'>
          <DisclosureSummary>仕組み</DisclosureSummary>
          <div className='pl-7'>
            <p>
              生成AIの機能を活用し、図を作成するよう入力プロンプトに指示して図を返答させています。特別な文書は読み込ませていません。利用するモデルは管理者の設定により切り替えられます。
            </p>
          </div>
        </Disclosure>
        </div>
      </Disclosure>
    </div>
  );
};
