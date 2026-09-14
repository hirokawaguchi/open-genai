import { useMemo } from 'react';
import { FILE_LIMIT } from '@/features/chat/constants';
import { useSelectedModel } from '@/hooks/useSelectedModel';
import { MODELS } from '@/models';

/** メタデータ未登録のローカルモデル向け。backend がテキスト抽出するため doc は有効。 */
const UNKNOWN_LOCAL_FLAGS = { text: true, doc: true, image: false, video: false };

export const useFileUploadable = () => {
  // Open GENAI: 添付可否は「AIモデル」ドロップダウンで選択中のモデルに連動させる
  // （生成時に参照するモデルと一致させるため）。
  const { selectedModelId } = useSelectedModel();

  const modelId = selectedModelId;

  const accept = useMemo(() => {
    if (!modelId) {
      return [];
    }

    const feature = MODELS.modelMetadata[modelId]?.flags ?? UNKNOWN_LOCAL_FLAGS;
    return [
      ...(feature.doc ? FILE_LIMIT.accept.doc : []),
      ...(feature.image ? FILE_LIMIT.accept.image : []),
      ...(feature.video ? FILE_LIMIT.accept.video : []),
    ];
  }, [modelId]);

  const fileUploadable = accept.length > 0;

  return {
    accept,
    fileUploadable,
  };
};
