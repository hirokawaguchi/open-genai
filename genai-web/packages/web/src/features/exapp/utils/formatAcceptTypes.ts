type MediaCategory = 'image' | 'document' | 'video' | 'audio' | 'other';

const MIME_TYPE_LABELS: Record<string, { category: MediaCategory; label: string }> = {
  // 画像
  'image/png': { category: 'image', label: 'PNG' },
  'image/jpeg': { category: 'image', label: 'JPEG' },
  'image/webp': { category: 'image', label: 'WebP' },
  'image/gif': { category: 'image', label: 'GIF' },
  'image/svg+xml': { category: 'image', label: 'SVG' },
  'image/bmp': { category: 'image', label: 'BMP' },
  'image/tiff': { category: 'image', label: 'TIFF' },
  'image/heic': { category: 'image', label: 'HEIC' },
  'image/heif': { category: 'image', label: 'HEIF' },
  'image/avif': { category: 'image', label: 'AVIF' },

  // ドキュメント
  'application/pdf': { category: 'document', label: 'PDF' },
  'text/plain': { category: 'document', label: 'テキスト' },
  'text/markdown': { category: 'document', label: 'Markdown' },
  'text/x-markdown': { category: 'document', label: 'Markdown' },
  'text/csv': { category: 'document', label: 'CSV' },
  'text/html': { category: 'document', label: 'HTML' },
  'application/json': { category: 'document', label: 'JSON' },
  'application/xml': { category: 'document', label: 'XML' },
  'text/xml': { category: 'document', label: 'XML' },
  'application/msword': { category: 'document', label: 'Word' },
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': {
    category: 'document',
    label: 'Word',
  },
  'application/vnd.ms-excel': { category: 'document', label: 'Excel' },
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {
    category: 'document',
    label: 'Excel',
  },
  'application/vnd.ms-powerpoint': { category: 'document', label: 'PowerPoint' },
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': {
    category: 'document',
    label: 'PowerPoint',
  },

  // 動画
  'video/mp4': { category: 'video', label: 'MP4' },
  'video/webm': { category: 'video', label: 'WebM' },
  'video/quicktime': { category: 'video', label: 'MOV' },
  'video/mpeg': { category: 'video', label: 'MPEG' },
  'video/mpegs': { category: 'video', label: 'MPEG' },
  'video/mpg': { category: 'video', label: 'MPEG' },
  'video/x-flv': { category: 'video', label: 'FLV' },
  'video/x-ms-wmv': { category: 'video', label: 'WMV' },
  'video/wmv': { category: 'video', label: 'WMV' },
  'video/3gpp': { category: 'video', label: '3GPP' },
  'video/x-msvideo': { category: 'video', label: 'AVI' },
  'video/x-matroska': { category: 'video', label: 'MKV' },

  // 音声
  'audio/mpeg': { category: 'audio', label: 'MP3' },
  'audio/mp3': { category: 'audio', label: 'MP3' },
  'audio/mpga': { category: 'audio', label: 'MP3' },
  'audio/mp4': { category: 'audio', label: 'M4A' },
  'audio/x-m4a': { category: 'audio', label: 'M4A' },
  'audio/m4a': { category: 'audio', label: 'M4A' },
  'audio/wav': { category: 'audio', label: 'WAV' },
  'audio/x-wav': { category: 'audio', label: 'WAV' },
  'audio/aac': { category: 'audio', label: 'AAC' },
  'audio/x-aac': { category: 'audio', label: 'AAC' },
  'audio/flac': { category: 'audio', label: 'FLAC' },
  'audio/opus': { category: 'audio', label: 'Opus' },
  'audio/ogg': { category: 'audio', label: 'OGG' },
  'audio/webm': { category: 'audio', label: 'WebM' },
  'audio/x-ms-wma': { category: 'audio', label: 'WMA' },
  'audio/wma': { category: 'audio', label: 'WMA' },
  'audio/aiff': { category: 'audio', label: 'AIFF' },
  'audio/x-aiff': { category: 'audio', label: 'AIFF' },
  'audio/amr': { category: 'audio', label: 'AMR' },
  'audio/L16': { category: 'audio', label: 'PCM' },
  'audio/pcm': { category: 'audio', label: 'PCM' },
};

const EXTENSION_LABELS: Record<string, { category: MediaCategory; label: string }> = {
  // 画像
  '.png': { category: 'image', label: 'PNG' },
  '.jpg': { category: 'image', label: 'JPEG' },
  '.jpeg': { category: 'image', label: 'JPEG' },
  '.webp': { category: 'image', label: 'WebP' },
  '.gif': { category: 'image', label: 'GIF' },
  '.svg': { category: 'image', label: 'SVG' },
  '.bmp': { category: 'image', label: 'BMP' },
  '.tiff': { category: 'image', label: 'TIFF' },
  '.heic': { category: 'image', label: 'HEIC' },
  '.heif': { category: 'image', label: 'HEIF' },
  '.avif': { category: 'image', label: 'AVIF' },

  // ドキュメント
  '.pdf': { category: 'document', label: 'PDF' },
  '.txt': { category: 'document', label: 'テキスト' },
  '.md': { category: 'document', label: 'Markdown' },
  '.csv': { category: 'document', label: 'CSV' },
  '.html': { category: 'document', label: 'HTML' },
  '.json': { category: 'document', label: 'JSON' },
  '.xml': { category: 'document', label: 'XML' },
  '.doc': { category: 'document', label: 'Word' },
  '.docx': { category: 'document', label: 'Word' },
  '.xls': { category: 'document', label: 'Excel' },
  '.xlsx': { category: 'document', label: 'Excel' },
  '.ppt': { category: 'document', label: 'PowerPoint' },
  '.pptx': { category: 'document', label: 'PowerPoint' },

  // 動画
  '.mp4': { category: 'video', label: 'MP4' },
  '.webm': { category: 'video', label: 'WebM' },
  '.mov': { category: 'video', label: 'MOV' },
  '.mpeg': { category: 'video', label: 'MPEG' },
  '.mpg': { category: 'video', label: 'MPEG' },
  '.flv': { category: 'video', label: 'FLV' },
  '.wmv': { category: 'video', label: 'WMV' },
  '.3gp': { category: 'video', label: '3GPP' },
  '.avi': { category: 'video', label: 'AVI' },
  '.mkv': { category: 'video', label: 'MKV' },

  // 音声
  '.mp3': { category: 'audio', label: 'MP3' },
  '.m4a': { category: 'audio', label: 'M4A' },
  '.wav': { category: 'audio', label: 'WAV' },
  '.aac': { category: 'audio', label: 'AAC' },
  '.flac': { category: 'audio', label: 'FLAC' },
  '.opus': { category: 'audio', label: 'Opus' },
  '.ogg': { category: 'audio', label: 'OGG' },
  '.wma': { category: 'audio', label: 'WMA' },
  '.aiff': { category: 'audio', label: 'AIFF' },
  '.aif': { category: 'audio', label: 'AIFF' },
  '.amr': { category: 'audio', label: 'AMR' },
  '.pcm': { category: 'audio', label: 'PCM' },
};

const CATEGORY_LABELS: Record<MediaCategory, string> = {
  image: '画像',
  document: 'ドキュメント',
  video: '動画',
  audio: '音声',
  other: 'ファイル',
};

const CATEGORY_ORDER: MediaCategory[] = ['image', 'document', 'video', 'audio', 'other'];

/**
 * accept 属性の値を人間が読みやすい形式にフォーマットする
 * @example
 * formatAcceptTypes('image/png,image/jpeg,application/pdf')
 * // => '対応ファイル：PNG/JPEG形式の画像、PDF形式のドキュメント'
 */
export const formatAcceptTypes = (accept: string): string => {
  if (!accept.trim()) {
    return '';
  }

  const patterns = accept
    .split(',')
    .map((p) => p.trim())
    .filter((p) => p !== '');
  const categories: Record<MediaCategory, Set<string>> = {
    image: new Set(),
    document: new Set(),
    video: new Set(),
    audio: new Set(),
    other: new Set(),
  };

  for (const pattern of patterns) {
    // ワイルドカード（image/*, video/* など）
    if (pattern.endsWith('/*')) {
      const mainType = pattern.split('/')[0];
      switch (mainType) {
        case 'image':
          categories.image.add('すべての画像');
          break;
        case 'video':
          categories.video.add('すべての動画');
          break;
        case 'audio':
          categories.audio.add('すべての音声');
          break;
        case 'text':
        case 'application':
          categories.document.add('すべてのドキュメント');
          break;
        default:
          categories.other.add('すべてのファイル');
      }
      continue;
    }

    // MIME タイプ
    if (MIME_TYPE_LABELS[pattern]) {
      const { category, label } = MIME_TYPE_LABELS[pattern];
      categories[category].add(label);
      continue;
    }

    // 拡張子
    if (pattern.startsWith('.')) {
      const ext = pattern.toLowerCase();
      if (EXTENSION_LABELS[ext]) {
        const { category, label } = EXTENSION_LABELS[ext];
        categories[category].add(label);
        continue;
      }
      // 未知の拡張子
      categories.other.add(ext.toUpperCase().slice(1));
      continue;
    }

    // 未知の MIME タイプ
    categories.other.add(pattern);
  }

  const parts: string[] = [];

  for (const category of CATEGORY_ORDER) {
    const formats = categories[category];
    if (formats.size === 0) continue;

    const formatList = Array.from(formats);

    // 「すべての〇〇」がある場合はそれだけ表示
    const allFormats = formatList.find((f) => f.startsWith('すべての'));
    if (allFormats) {
      parts.push(allFormats);
    } else {
      const categoryLabel = CATEGORY_LABELS[category];
      parts.push(`${formatList.join('/')}形式の${categoryLabel}`);
    }
  }

  if (parts.length === 0) {
    return '';
  }

  return `対応ファイル：${parts.join('、')}`;
};
