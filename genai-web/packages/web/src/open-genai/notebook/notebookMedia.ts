import { teamApi } from '@/lib/fetcher';
import { mermaidToPngBase64 } from './mermaidPng';
import { sourceFilename } from './NotebookSourceHandoff';

const textToBase64 = (text: string) => {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
};

export const imageSrcToBase64 = async (src: string): Promise<string> => {
  if (src.startsWith('data:')) {
    const comma = src.indexOf(',');
    return comma >= 0 ? src.slice(comma + 1) : '';
  }
  const res = await fetch(src);
  if (!res.ok) return '';
  const bytes = new Uint8Array(await res.arrayBuffer());
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
};

const postFile = async (
  sessionId: string,
  filename: string,
  content: string,
  describe: boolean,
) => {
  await teamApi.post(`notebook/sessions/${encodeURIComponent(sessionId)}/files`, {
    filename,
    content,
    ...(describe ? {} : { describe: false }),
  });
};

/** 生成画像を参考資料にし、画像対応モデルが有効なら説明文も足す。 */
export const saveGeneratedImage = async (sessionId: string, label: string, src: string) => {
  const content = await imageSrcToBase64(src);
  if (!content) return '画像を読み取れませんでした。';
  try {
    await postFile(sessionId, sourceFilename('画像.png', label), content, true);
  } catch {
    return 'ノートに追加できませんでした。';
  }
  return null;
};

/** 図の Mermaid と PNG を参考資料に足す。 */
export const saveDiagramFiles = async (sessionId: string, label: string, code: string) => {
  const trimmed = code.trim();
  if (!trimmed) return '図がありません。';
  const mdName = sourceFilename('図.md', label || trimmed);
  const pngName = mdName.replace(/\.md$/i, '.png');
  const markdown = `# ${label.trim() || '図'}\n\n\`\`\`mermaid\n${trimmed}\n\`\`\`\n`;
  try {
    await postFile(sessionId, mdName, textToBase64(markdown), false);
    const png = await mermaidToPngBase64(trimmed);
    if (png) {
      await postFile(sessionId, pngName, png, false);
    }
  } catch {
    return 'ノートに追加できませんでした。';
  }
  return null;
};
