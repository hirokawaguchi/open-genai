import { Artifact } from 'genai-web';
import { useState } from 'react';
import { DownloadIcon } from '@/components/ui/icons/DownloadIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { download } from '@/utils/createDownloadLink';
import { useDownloadArtifactCarrier } from '../hooks/useDownloadArtifactCarrier';
import { getFileExtension } from '../utils/getFileExtension';

type Props = {
  artifacts?: Artifact[];
};

const isImage = (a: Artifact): boolean => Boolean(a.content);
const isCarrier = (a: Artifact): boolean => Boolean(a.object_key) && !a.file_url;

// AI アプリ成果物の表示。画像はインライン、ファイルはダウンロードボタンで提示する。
// carrier 配信（LGWAN 想定）では本体 URL を UI に出さず、URL を記載した
// 「リンクファイル」を取得させ、別端末で開く運用を案内する。
export const ExAppArtifactDownloads = ({ artifacts }: Props) => {
  const [loadingKeys, setLoadingKeys] = useState<string[]>([]);
  const { downloadCarrier } = useDownloadArtifactCarrier();

  if (!artifacts || artifacts.length === 0) {
    return null;
  }

  const images = artifacts.filter(isImage);
  const files = artifacts.filter((a) => !isImage(a));
  const hasCarrier = files.some(isCarrier);

  const handleCarrier = async (objectKey: string) => {
    setLoadingKeys((prev) => [...prev, objectKey]);
    try {
      await downloadCarrier(objectKey);
    } catch (error) {
      console.error('Error downloading link file:', error);
    } finally {
      setLoadingKeys((prev) => prev.filter((k) => k !== objectKey));
    }
  };

  return (
    <div className='mt-4 space-y-4'>
      {images.map((artifact, index) => (
        <img
          className='my-4 h-auto w-fit max-w-sm object-cover'
          src={`data:image/${getFileExtension(artifact.display_name)};base64,${artifact.content}`}
          alt={artifact.display_name}
          key={`${artifact.display_name}-${index}`}
        />
      ))}

      {files.length > 0 && (
        <dl className='border-t border-t-solid-gray-420 pt-4'>
          <dt className='mb-2 text-std-17B-170'>ファイル一覧:</dt>
          {hasCarrier && (
            <p className='mb-3 rounded-8 bg-blue-50 p-3 text-dns-14N-130 leading-175 text-solid-gray-700'>
              LGWAN 端末からは成果物を直接ダウンロードできません。「リンクファイル」を保存し、
              データ持ち出し経路でインターネット接続端末へ移してから、ファイル内の URL で取得してください。
              URL の有効期限はリンクファイル内に記載しています。
            </p>
          )}
          <dd>
            <ul className='space-y-4'>
              {files.map((artifact, index) => {
                if (isCarrier(artifact)) {
                  const key = artifact.object_key as string;
                  const isDownloading = loadingKeys.includes(key);
                  return (
                    <li key={`${key}-${index}`}>
                      <LoadingButton
                        type='button'
                        loading={isDownloading}
                        onClick={() => handleCarrier(key)}
                        variant='outline'
                        size='md'
                      >
                        {!isDownloading && <DownloadIcon aria-hidden={true} />}
                        {artifact.display_name} のリンクファイル
                        <span className='sr-only'>をダウンロード</span>
                      </LoadingButton>
                    </li>
                  );
                }
                if (artifact.file_url) {
                  return (
                    <li key={`${artifact.file_url}-${index}`}>
                      <LoadingButton
                        type='button'
                        onClick={() => download(artifact.file_url as string, artifact.display_name)}
                        variant='outline'
                        size='md'
                      >
                        <DownloadIcon aria-hidden={true} />
                        {artifact.display_name}
                        <span className='sr-only'>をダウンロード</span>
                      </LoadingButton>
                    </li>
                  );
                }
                return null;
              })}
            </ul>
          </dd>
        </dl>
      )}
    </div>
  );
};
