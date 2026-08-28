import {
  DeleteFileResponse,
  GetFileDownloadSignedUrlRequest,
  GetFileDownloadSignedUrlResponse,
  GetFileUploadSignedUrlRequest,
  GetFileUploadSignedUrlResponse,
  UploadFileRequest,
} from 'genai-web';
import { genUApi, readUploadPutJson, uploadToSignedUrl } from '@/lib/fetcher';
import type { UploadPutResponse } from '@/lib/fetcher';
import { fileObjectKeyFromUrl } from '@/lib/fileUrl';

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
  return genUApi.post<GetFileUploadSignedUrlResponse>('file/url', {
    filename: req.filename,
    mediaFormat: req.mediaFormat,
    operation: 'upload',
  } as GetFileUploadSignedUrlRequest & { operation: string });
};

export const uploadFile = async (
  url: string,
  req: UploadFileRequest,
): Promise<UploadPutResponse> => {
  const res = await uploadToSignedUrl(url, req.file, 'file/*');
  return readUploadPutJson(res);
};

const mintLocalFileUrl = async (
  key: string,
  operation: 'download' | 'delete',
): Promise<string> => {
  const { data: url } = await genUApi.post<string>('file/url', {
    key,
    filename: key.split('/').pop() || key,
    operation,
  });
  return url;
};

export const getFileDownloadSignedUrl = async (s3Url: string) => {
  // Open GENAI: ローカル /files は HMAC 付き URL を都度発行する
  if (/^https?:\/\//.test(s3Url) || s3Url.startsWith('/')) {
    const key = fileObjectKeyFromUrl(
      s3Url.startsWith('/') ? `${window.location.origin}${s3Url}` : s3Url,
    );
    if (key) {
      return mintLocalFileUrl(key, 'download');
    }
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
  // オブジェクトキー（`<uuid>/<name>`）から DELETE 用署名 URL を発行して削除する。
  const key = fileName.replace(/^\/+/, '').replace(/^files\//, '');
  const signedUrl = await mintLocalFileUrl(key, 'delete');
  const res = await fetch(signedUrl, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(`Failed to delete file: ${res.status}`);
  }
  return { data: null as DeleteFileResponse, status: res.status };
};

export const getS3Uri = (s3Url: string) => {
  const { bucketName, prefix } = parseS3Url(s3Url);
  return `s3://${bucketName}/${prefix}`;
};
