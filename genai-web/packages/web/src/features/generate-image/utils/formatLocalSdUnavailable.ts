import { findModelDisplayNameByModelId } from '@/models';

const LOCAL_SD_MODEL_ID = 'local-sd';

/** local-sd 不通時に、その画面で選べる他モデル名から利用者向け文面を組み立てる。 */
export const formatLocalSdUnavailableMessage = (imageGenModelIds: string[]): string => {
  const base = 'ローカルの Stable Diffusion に接続できません。';
  const askAdmin =
    'ローカルで生成する場合は、管理者に Stable Diffusion の起動を依頼してください。';
  const others = imageGenModelIds
    .filter((modelId) => modelId !== LOCAL_SD_MODEL_ID)
    .map((modelId) => findModelDisplayNameByModelId(modelId));
  if (others.length === 0) {
    return `${base}${askAdmin}`;
  }
  return `${base}入力欄の上の「画像」から ${others.join('、')} を選んで、もう一度生成してください。${askAdmin}`;
};
