import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { ModelSelector } from './ModelSelector';

export const TranslateHeader = () => {
  return (
    <div className='mb-6 flex flex-col gap-4'>
      <ManagedAppHeader
        teamId={COMMON_EXAPPS_TEAM_ID}
        exAppId='translate'
        fallbackTitle='翻訳'
        fallbackDescription='手元の文章を他の言語に翻訳'
        fallbackHowTo={
          <div className='prose prose-sm mt-3 max-w-full'>
            <h2>想定用途</h2>
            <p>
              生成AI（上部で選択中のモデル）を使って、翻訳サービスを提供するものです。
              文章を英語/日本語/中国語/韓国語/フランス語/スペイン語/ドイツ語のいずれかに翻訳することができます。
              カジュアルな文章がほしいなどのコンテキストを追加することもできます。
            </p>
            <h3>アプリ個別の留意点</h3>
            <p>
              長文を入力する場合は処理が著しく重くなる場合がありますので、その場合は、分割して入力してください。翻訳の正確性の確認は利用者側の責任です。翻訳後の文章を再翻訳して大意が変わってないことを確認する等の工夫をお願いします。
            </p>
            <h3>入力例</h3>
            <p>翻訳したい文章のみを入力してください。</p>
            <h2>操作方法</h2>
            <p>
              テキストの箇所に翻訳したいテキストを入力します。翻訳する言語は、プルダウンから選択してください。翻訳して、といったAIへの指示は不要です。
              <br />
              AIモデルのプルダウンより利用するAIモデルを選択してください。利用するAIモデルによって、翻訳結果が変わることがあります。
            </p>
            <Disclosure className='my-4'>
              <DisclosureSummary>仕組み</DisclosureSummary>
              <div className='pl-7'>
                <p>
                  生成AIの機能を活用し、翻訳するよう入力プロンプトに指示して翻訳文を返答させています。特別な文書は読み込ませていません。利用するモデルは管理者の設定により切り替えられます。
                </p>
              </div>
            </Disclosure>
          </div>
        }
      >
        <ModelSelector />
      </ManagedAppHeader>
    </div>
  );
};
