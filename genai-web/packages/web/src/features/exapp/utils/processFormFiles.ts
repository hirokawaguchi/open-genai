import { convertFileToBase64 } from './convertFileToBase64';

type ProcessedFile = {
  key: string;
  files: { filename: string; content: string }[];
};

/**
 * フォームデータからFileList型のフィールドを抽出し、Base64エンコードされたファイルデータに変換する
 * @param data - フォームデータ
 * @returns Base64エンコードされたファイルデータの配列
 */
export const processFormFiles = async (data: Record<string, unknown>): Promise<ProcessedFile[]> => {
  const result: ProcessedFile[] = [];

  for (const key of Object.keys(data)) {
    const value = data[key];

    // FileList、File[]、または File 1件を受け付ける
    const isFileList = typeof FileList !== 'undefined' && value instanceof FileList;
    const isFileArray = Array.isArray(value) && value.length > 0 && value[0] instanceof File;
    const isFile = typeof File !== 'undefined' && value instanceof File;

    if (!isFileList && !isFileArray && !isFile) {
      continue;
    }

    const files = isFileList
      ? Array.from(value as FileList)
      : isFile
        ? [value as File]
        : (value as File[]);

    if (files.length === 0) {
      continue;
    }

    const processedFiles: { filename: string; content: string }[] = [];

    for (const file of files) {
      const base64 = await convertFileToBase64(file);
      processedFiles.push({
        filename: file.name,
        content: base64,
      });
    }

    result.push({
      key,
      files: processedFiles,
    });
  }

  return result;
};
