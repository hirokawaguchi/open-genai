import { PiBookOpenBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ModelSelector } from './ModelSelector';

export const GenerateTextHeader = () => {
  return (
    <div className='mb-6 flex flex-col gap-4'>
      <BreadcrumbsNav
        items={[
          { label: 'ホーム', to: '/' },
          { label: 'AIアプリ', to: '/apps' },
          { label: '文章を生成' },
        ]}
      />
      <h1 className='flex justify-start text-std-20B-160 lg:text-std-24B-150'>文章を生成</h1>
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
          ビジネスメールや記事などの文章をAIが代行して作成することができます。文書のドラフティングに役立ちます。
        </p>
        <h3>アプリ個別の留意点</h3>
        <p>本アプリは生成AIを使用しています。以下のリスクと対応をご理解ください：</p>
        <Disclosure className='my-4'>
          <DisclosureSummary>リスクの例と対応アクション</DisclosureSummary>
          <div className='pl-7'>
            <dl>
              <div>
                <dt className='mb-2 font-bold'>リスクの例：</dt>
                <dd className='ml-0'>
                  <ul>
                    <li>ハルシネーション（でたらめ）：事実と異なる不正確な情報を生成するおそれ</li>
                    <li>最新性の欠如：古い情報に基づく回答を生成するおそれ</li>
                    <li>バイアス：偏った見解や政府の公式見解と異なる判断を生成するおそれ</li>
                    <li>著作権侵害：保護された著作物を不適切に生成するおそれ</li>
                    <li>倫理的問題：道徳的に問題のある判断や提案を生成するおそれ</li>
                    <li>
                      再現性や説明可能性の欠如：同じ質問でも異なる回答を生成し、生成された内容の根拠も不明なおそれ
                    </li>
                  </ul>
                </dd>
              </div>
              <div>
                <dt className='mb-2 font-bold'>対応アクション：</dt>
                <dd className='ml-0'>
                  <ul>
                    <li>
                      常に出力内容を批判的に評価し、利用者自身で正確性・妥当性等を判断してください
                    </li>
                    <li>機密性３情報や業務目的以外の私的利用の情報の入力は避けてください</li>
                    <li>必ず他の信頼できる情報源を確認してください</li>
                  </ul>
                </dd>
              </div>
            </dl>
          </div>
        </Disclosure>
        <h3>入力例</h3>
        <p>
          文章の元になる情報のところに生成したい文章のキーワード等と、例を参考に文章の形式に入力された情報を自然言語で入力してください。
        </p>
        <h2>操作方法</h2>
        <p>
          必要な情報を入力し、実行ボタンを押します。AIモデルのプルダウンより利用するAIモデルを選択してください。利用するAIモデルによって、生成結果が変わることがあります。
          <br />
          なお、情報が多すぎる場合は処理が著しく重くなる場合がありますので、その場合は情報を減らして入力してください。
        </p>
        <Disclosure className='my-4'>
          <DisclosureSummary>仕組み</DisclosureSummary>
          <div className='pl-7'>
            <p>
              上部で選択した生成AIモデルを使い、文章の元になる情報および文章の形式に入力された情報をもとに文章を生成するよう指示し、生成された文章を返しています。特別な文書は読み込ませていません。利用するモデルは管理者の設定により切り替えられます。
            </p>
          </div>
        </Disclosure>
        </div>
      </Disclosure>
    </div>
  );
};
