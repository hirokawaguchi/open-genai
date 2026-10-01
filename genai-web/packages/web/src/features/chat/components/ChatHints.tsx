import { useSubmitKey } from '@/hooks/useSubmitKey';

export const ChatHints = () => {
  const { hint } = useSubmitKey();
  return (
    <dl className='flex flex-col gap-4 text-std-16N-170 text-solid-gray-800'>
      <div>
        <dt className='mb-1 text-std-16B-150'>チャットの使い方</dt>
        <dd>
          入力欄にメッセージを書いて送信すると、AIから回答が返ってきます。{hint}
          です。質問・依頼・相談など、業務に関することを自由に送ってみてください。回答後もそのまま会話を続けられます。
        </dd>
      </div>
      <div>
        <dt className='mb-1 text-std-16B-150'>AIモデルを切り替える</dt>
        <dd>
          入力欄の上にあるAIモデルから、目的に合わせて切り替えられます。
        </dd>
      </div>
      <div>
        <dt className='mb-1 text-std-16B-150'>システムプロンプトを使う</dt>
        <dd>
          「システムプロンプト」は、会話の前にAIへ渡す役割の指示です。一覧から選ぶか、自分で書いて保存できます。会話を始めたあとは編集できません。
        </dd>
      </div>
      <div>
        <dt className='mb-1 text-std-16B-150'>ファイルを添付して質問する</dt>
        <dd>
          資料を添付して質問できます（4.5MBまで）。対応形式は JPEG / PNG / WebP / GIF、PDF / テキスト / CSV / HTML / Markdown / Word / Excel です。
        </dd>
      </div>
    </dl>
  );
};
