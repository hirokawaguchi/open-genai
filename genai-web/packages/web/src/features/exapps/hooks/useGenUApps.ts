import { useImageAvailable } from '@/open-genai/image-health/useImageAvailable';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';
import { useExAppCatalog } from './useExAppCatalog';
import { isCatalogListed } from '../utils/builtinExApp';
import { ExAppOptions } from '../types';

export const useGenUApps = () => {
  // 画像生成は SD サーバの稼働状況に応じて出し分ける（他アプリのヘルスチェックに準拠）
  const imageAvailable = useImageAvailable();
  const { apps, loaded } = useExAppCatalog();
  const metaById = new Map(
    apps.map((a) => [
      a.exAppId,
      {
        name: (a.exAppName || '').trim(),
        description: (a.description || '').trim(),
      },
    ]),
  );
  const nameOf = (id: string, fallback: string) => metaById.get(id)?.name || fallback;
  const descOf = (id: string, fallback: string) => metaById.get(id)?.description || fallback;
  const listed = (id: string) => isCatalogListed(id, apps, loaded);

  const genUApps: ExAppOptions[string]['exApps'] = [];

  if (listed('chat')) {
    genUApps.push({
      label: nameOf('chat', 'チャット'),
      value: 'chat',
      description: descOf('chat', '着想や整理のための壁打ち'),
    });
  }
  if (isUseCaseEnabled('generate') && listed('generate')) {
    genUApps.push({
      label: nameOf('generate', '文章を生成'),
      value: 'generate',
      description: descOf('generate', '手元の情報をもとに文章を作成'),
    });
  }
  if (isUseCaseEnabled('translate') && listed('translate')) {
    genUApps.push({
      label: nameOf('translate', '翻訳'),
      value: 'translate',
      description: descOf('translate', '手元の文章を他の言語に翻訳'),
    });
  }
  if (isUseCaseEnabled('image') && imageAvailable && listed('image')) {
    genUApps.push({
      label: nameOf('image', '画像を生成'),
      value: 'image',
      description: descOf('image', '文章や単語から画像を生成'),
    });
  }
  if (isUseCaseEnabled('diagram') && listed('diagram')) {
    genUApps.push({
      label: nameOf('diagram', 'ダイアグラムを生成'),
      value: 'diagram',
      description: descOf('diagram', 'テキストからフローチャートやマインドマップを作成'),
    });
  }
  if (listed('knowledge')) {
    // 旧 rag-tags / rag-register / rag-maintain を集約した専用ページ。
    genUApps.push({
      label: nameOf('knowledge', 'ナレッジ管理'),
      value: 'knowledge',
      description: descOf(
        'knowledge',
        '共有・所属チームの資料を登録／管理（検索は「ナレッジ検索」）',
      ),
    });
  }
  // 文字起こし(transcribe)はクラウド(Amazon Transcribe)依存のため除外。
  // ローカルの「文字起こし（ローカル Whisper）」AIアプリで代替している。

  return { genUApps };
};
