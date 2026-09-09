import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { ModelSelector } from './ModelSelector';

export const DiagramHeader = () => {
  return (
    <div className='mb-6 flex flex-col gap-4'>
      <ManagedAppHeader
        teamId={COMMON_EXAPPS_TEAM_ID}
        exAppId='diagram'
        fallbackTitle='ダイアグラムを生成'
        fallbackDescription='テキストからフローチャートやマインドマップを作成'
        fallbackHowTo={
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
              図にしたい任意の文章を入力します。AIを選択すると、生成AIが適切な図を選択し、生成します。AIモデルのプルダウンより利用するAIモデルを選択してください。利用するモデルによって、結果が変わることがあります。
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
        }
      >
        <ModelSelector />
      </ManagedAppHeader>
    </div>
  );
};
