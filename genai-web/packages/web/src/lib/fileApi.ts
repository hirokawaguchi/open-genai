import {
  DeleteFileResponse,
  GetFileDownloadSignedUrlRequest,
  GetFileDownloadSignedUrlResponse,
  GetFileUploadSignedUrlRequest,
  GetFileUploadSignedUrlResponse,
  UploadFileRequest,
} from 'genai-web';
import { genUApi, uploadToSignedUrl } from '@/lib/fetcher';

const parseS3Url = (s3Url: string) => {
  let result = /^s3:\/\/(?<bucketName>.+?)\/(?<prefix>.+)/.exec(s3Url);

  if (!result) {
    result = /^https:\/\/s3.(?<region>.+?).amazonaws.com\/(?<bucketName>.+?)\/(?<prefix>.+)$/.exec(
      s3Url,
    );

    if (!result) {
      result =
        /^https:\/\/(?<bucketName>.+?).s3(|(\.|-)(?<region>.+?)).amazonaws.com\/(?<prefix>.+)$/.exec(
          s3Url,
        );
    }
  }

  return result?.groups as {
    bucketName: string;
    prefix: string;
    region?: string;
  };
};

export const getSignedUrl = (req: GetFileUploadSignedUrlRequest) => {
  return genUApi.post<GetFileUploadSignedUrlResponse>('file/url', req);
};

export const uploadFile = (url: string, req: UploadFileRequest) => {
  return uploadToSignedUrl(url, req.file, 'file/*');
};

export const getFileDownloadSignedUrl = async (s3Url: string) => {
  // Open GENAI: ローカル版ではファイルは http(s) URL で直接配信されるため、
  // S3 署名付き URL 取得は行わずそのまま返す。
  if (/^https?:\/\//.test(s3Url)) {
    return s3Url;
  }

  const { bucketName, prefix, region } = parseS3Url(s3Url);

  const [filePrefix, anchorLink] = prefix.split('#');

  const params: GetFileDownloadSignedUrlRequest = {
    bucketName: bucketName,
    filePrefix: decodeURIComponent(filePrefix),
    region: region,
  };
  const { data: url } = await genUApi.get<GetFileDownloadSignedUrlResponse>('/file/url', {
    params,
  });
  return `${url}${anchorLink ? `#${anchorLink}` : ''}`;
};

export const deleteUploadedFile = async (fileName: string) => {
  // PUT/GET と同じ `/files/<key>` を使う（認証不要の公開パス）。
  // fileName はオブジェクトキー（`<uuid>/<name>`）。スラッシュは区切りとして残す。
  const key = fileName.replace(/^\/+/, '').replace(/^files\//, '');
  const encoded = key
    .split('/')
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join('/');
  return genUApi.delete<DeleteFileResponse>(`files/${encoded}`);
};

export const getS3Uri = (s3Url: string) => {
  const { bucketName, prefix } = parseS3Url(s3Url);
  return `s3://${bucketName}/${prefix}`;
};
