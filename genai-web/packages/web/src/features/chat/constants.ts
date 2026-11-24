import { FileLimit } from 'genai-web';

export const FILE_LIMIT: FileLimit = {
  accept: {
    doc: ['.csv', '.doc', '.docx', '.html', '.md', '.pdf', '.txt', '.xls', '.xlsx', '.gif'],
    image: ['.jpg', '.jpeg', '.png', '.webp'],
    video: ['.mkv', '.mov', '.mp4', '.webm'],
  },
  maxFileCount: 5,
  // 文書の読み取り上限（MAX_DOC_BYTES、20MiB）に揃える。比較は 10^6 バイト単位。
  maxFileSizeMB: 20,
  maxImageFileCount: 20,
  maxImageFileSizeMB: 3.75,
  maxVideoFileCount: 1,
  maxVideoFileSizeMB: 1000, // 1 GB for S3 input
} as const;
