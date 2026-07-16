import { PiBookOpenBold } from 'react-icons/pi';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';

export const ChatHints = () => {
  return (
    <div className='w-full rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3 text-solid-gray-800'>
      <Disclosure>
        <DisclosureSummary>
          <h2 className='flex items-center text-std-16B-150'>
            <PiBookOpenBold className='mr-2 size-5 flex-none' />
            使い方（クリックで開閉）
          </h2>
        </DisclosureSummary>
        <dl className='mt-4 flex flex-col gap-4 xl:gap-6'>
          <div>
          <dt className='mb-2 text-std-18B-160'>チャットの使い方</dt>
          <dd>
            下部の入力欄にメッセージを入力して送信すると、AIから回答が返ってきます。Enter
            で送信、Shift+Enter
            で改行できます。質問・依頼・相談など、業務に関することを自由に送ってみてください。一度の質問で完結しなくても大丈夫です。回答後もそのまま会話を続けることで、タスクをより深く進められます。
          </dd>
        </div>
        <div>
          <dt className='mb-2 text-std-18B-160'>AIモデルを切り替える</dt>
          <dd>
            画面上部のAIモデル選択から、複数のAIモデルを切り替えて利用できます。モデルによって特性が異なりますので、目的に応じて使い分けてみてください。
          </dd>
        </div>
        <div>
          <dt className='mb-2 text-std-18B-160'>システムプロンプトを使う</dt>
          <dd>
            画面上部の「システムプロンプト」とは、会話が始まる前にAIへ与える事前指示です。「法令の専門家として回答してください」のように設定すると、AIがその役割で一貫して対話します。毎回同じ指示を入力する手間が省けるため、用途に合わせた使い方が可能です。あらかじめ用意された一覧から選ぶか、自分で作成・保存することもできます。
          </dd>
        </div>
        <div>
          <dt className='mb-2 text-std-18B-160'>ファイルを添付して質問する</dt>
          <dd>
            資料や文書をファイルに添付してAIに質問できます（4.5MBまで）。文書の要約・翻訳・分析など、ファイルの内容を踏まえた詳細な回答が得られます。対応形式はJPEG/PNG/WebP/GIF形式の画像、PDF/テキスト/CSV/HTML/Markdown/Word/Excel形式のドキュメントです。
          </dd>
        </div>
        </dl>
      </Disclosure>
    </div>
  );
};
