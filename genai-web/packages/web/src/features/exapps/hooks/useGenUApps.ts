import { useImageAvailable } from '@/open-genai/image-health/useImageAvailable';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';
import { ExAppOptions } from '../types';

export const useGenUApps = () => {
  // 画像生成は SD サーバの稼働状況に応じて出し分ける（他アプリのヘルスチェックに準拠）
  const imageAvailable = useImageAvailable();

  const genUApps: ExAppOptions[string]['exApps'] = [
    {
      label: 'チャット',
      value: 'chat',
      description: '着想や整理のための壁打ち',
    },
    {
      label: '文章を生成',
      value: 'generate',
      description: '手元の情報をもとに文章を作成',
    },
    ...(isUseCaseEnabled('translate')
      ? [
          {
            label: '翻訳',
            value: 'translate',
            description: '手元の文章を他の言語に翻訳',
          },
        ]
      : []),

    ...(isUseCaseEnabled('image') && imageAvailable
      ? [
          {
            label: '画像を生成',
            value: 'image',
            description: '文章や単語から画像を生成',
          },
        ]
      : []),
    ...(isUseCaseEnabled('diagram')
      ? [
          {
            label: 'ダイアグラムを生成',
            value: 'diagram',
            description: 'テキストからフローチャートやマインドマップを作成',
          },
        ]
      : []),
    // 文字起こし(transcribe)はクラウド(Amazon Transcribe)依存のため除外。
    // ローカルの「文字起こし（ローカル Whisper）」AIアプリで代替している。
  ];

  return { genUApps };
};
