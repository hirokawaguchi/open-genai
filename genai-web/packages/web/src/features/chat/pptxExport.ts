import { predict } from '@/lib/chatApi';
import { ApiError, genUApi } from '@/lib/fetcher';
import { mermaidToPngDataUrl } from '@/features/exapp/utils/mermaid';
import { newId } from '@/utils/uuid';

const SLIDE_SYSTEM = `あなたはスライドの構成係です。利用者の指示を最優先し、渡された回答だけを材料に Markdown を書きます。
規則:
- 出力は Markdown だけ。説明や前置きは書かない。
- 1行目はデッキの題名を「# 題名」で書く。題名は指示に合わせる。
- 続く各スライドは「## 見出し」と、その直下の箇条書き。1つの ## が1枚。
- 指示に枚数があれば、## の数をその枚数にする。順序、強調、聞き手、言葉づかいも指示に従う。
- 回答の見出しや段落順をそのまま写さない。指示に合うものだけを選び、並べ、短くする。
- 回答に無い事実、数値、固有名は足さない。`;

const SLIDE_COUNT = /(\d+)\s*枚/;

export const slideCountRequested = (instruction: string): number | null => {
  const matched = instruction.match(SLIDE_COUNT);
  if (!matched) return null;
  const count = Number(matched[1]);
  if (!Number.isInteger(count) || count < 1 || count > 20) return null;
  return count;
};

export const countSlideHeadings = (markdown: string): number =>
  markdown.split('\n').filter((line) => /^##\s+\S/.test(line.trim())).length;

/** 先頭の `# 題名` を表紙に使い、残りを各スライドの原稿にする。 */
export const splitDeckTitle = (markdown: string): { title: string; body: string } => {
  const text = markdown.trim();
  const matched = text.match(/^#\s+([^\n]+)\n+([\s\S]+)$/);
  if (!matched) return { title: '回答', body: text };
  const title = matched[1]
    .replace(/^#+\s*/, '')
    .trim()
    .slice(0, 80);
  const body = matched[2].trim();
  return { title: title || '回答', body: body || text };
};

const MERMAID_FENCE = /```mermaid[^\n]*\n([\s\S]*?)```/g;

export const stripMarkdownFence = (text: string): string => {
  const trimmed = text.trim();
  const fenced = trimmed.match(/^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$/);
  return (fenced ? fenced[1] : trimmed).trim();
};

const requestSlideMarkdown = async (
  answer: string,
  instruction: string,
  modelId: string | undefined,
  correction: string,
): Promise<string> => {
  const raw = await predict({
    id: newId(),
    model: modelId ? { type: 'bedrock', modelId } : undefined,
    messages: [
      { role: 'system', content: SLIDE_SYSTEM },
      {
        role: 'user',
        content: `# 回答\n${answer.trim()}\n\n# 指示\n${instruction.trim()}${correction}\nこの指示に合わせて題名と各スライドを書け。回答の並びを写さない。`,
      },
    ],
  });
  return stripMarkdownFence(typeof raw === 'string' ? raw : String(raw ?? ''));
};

export const draftSlideMarkdown = async (
  answer: string,
  instruction: string,
  modelId?: string,
): Promise<string> => {
  const wanted = slideCountRequested(instruction);
  let draft = await requestSlideMarkdown(answer, instruction, modelId, '');
  const headings = countSlideHeadings(draft);
  const missingSlides = headings === 0;
  const wrongCount = wanted !== null && headings !== wanted;
  if (!missingSlides && !wrongCount) return draft;
  const correction = wrongCount
    ? `\n前回の ## は ${headings} 個だった。## をちょうど ${wanted} 個にする。`
    : '\n## の見出しが無い。各スライドを ## で書き分ける。';
  const retried = await requestSlideMarkdown(answer, instruction, modelId, correction);
  return retried.trim() ? retried : draft;
};

const pngBase64 = (dataUrl: string): string => {
  const comma = dataUrl.indexOf(',');
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
};

/** 原稿の mermaid をスライド用 PNG にし、画像参照へ差し替える。失敗した図はそのまま残す。 */
export const embedMermaidFences = async (
  markdown: string,
): Promise<{ markdown: string; assets: Record<string, string> }> => {
  const assets: Record<string, string> = {};
  let index = 0;
  const parts: string[] = [];
  let last = 0;
  for (const match of markdown.matchAll(MERMAID_FENCE)) {
    const start = match.index ?? 0;
    parts.push(markdown.slice(last, start));
    const path = `images/mermaid-${index}.png`;
    index += 1;
    try {
      assets[path] = pngBase64(await mermaidToPngDataUrl(match[1] ?? '', 2, { landscape: true }));
      parts.push(`![diagram](${path})`);
    } catch {
      parts.push(match[0]);
    }
    last = start + match[0].length;
  }
  parts.push(markdown.slice(last));
  return { markdown: parts.join(''), assets };
};

export type PptxComposeStatus = {
  status?: string;
  progress?: number;
  step?: string;
  error?: string;
  mermaid?: { path?: string; code?: string }[];
};

const errorText = (error: unknown, fallback: string): string => {
  if (error instanceof ApiError && error.data && typeof error.data === 'object') {
    const message = (error.data as { error?: unknown }).error;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return fallback;
};

export const startPptxCompose = async (
  markdown: string,
  assets: Record<string, string>,
  title: string,
  instruction: string,
): Promise<string> => {
  try {
    const res = await genUApi.post<{ jobId?: string }>('procuretech-generate/compose', {
      markdown,
      assets,
      title,
      instruction,
    });
    const jobId = res.data.jobId ?? '';
    if (!jobId) throw new Error('スライドの作成を開始できませんでした。');
    return jobId;
  } catch (error) {
    throw new Error(errorText(error, 'スライドの作成を開始できませんでした。'));
  }
};

export const fetchPptxCompose = async (jobId: string): Promise<PptxComposeStatus> => {
  try {
    const res = await genUApi.get<PptxComposeStatus>(`procuretech-generate/compose/${jobId}`);
    return res.data;
  } catch (error) {
    throw new Error(errorText(error, 'スライドの状況を取得できませんでした。'));
  }
};

export const postPptxMermaid = async (
  jobId: string,
  assets: Record<string, string>,
): Promise<void> => {
  try {
    await genUApi.post(`procuretech-generate/compose/${jobId}/mermaid`, { assets });
  } catch (error) {
    throw new Error(errorText(error, '図をスライドへ入れられませんでした。'));
  }
};

export const downloadPptx = async (jobId: string): Promise<Uint8Array> => {
  try {
    const { blob } = await genUApi.getBlob(`procuretech-generate/compose/${jobId}/file`);
    return new Uint8Array(await blob.arrayBuffer());
  } catch (error) {
    throw new Error(errorText(error, 'スライドを取得できませんでした。'));
  }
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** 合成の完了まで待ち、追加の mermaid は画像化して渡す。 */
export const waitForPptx = async (
  jobId: string,
  onStep: (step: string) => void,
  isCancelled: () => boolean,
): Promise<Uint8Array> => {
  const deadline = Date.now() + 15 * 60 * 1000;
  let mermaidPosted = false;
  while (Date.now() < deadline) {
    if (isCancelled()) throw new Error('cancelled');
    const status = await fetchPptxCompose(jobId);
    if (status.step) onStep(status.step);
    const phase = (status.status ?? '').toLowerCase();
    if (phase === 'error') {
      throw new Error(status.error || 'スライドを作れませんでした。');
    }
    if (phase === 'success') return downloadPptx(jobId);
    if (phase === 'need_mermaid' && !mermaidPosted) {
      const assets: Record<string, string> = {};
      for (const item of status.mermaid ?? []) {
        if (!item.path || !item.code) continue;
        try {
          assets[item.path] = pngBase64(
            await mermaidToPngDataUrl(item.code, 2, { landscape: true }),
          );
        } catch {
          // 1件失敗しても他の図は渡す。
        }
      }
      if (Object.keys(assets).length === 0) {
        throw new Error('図をスライド用の画像にできませんでした。');
      }
      onStep('図を画像化しています');
      await postPptxMermaid(jobId, assets);
      mermaidPosted = true;
      continue;
    }
    await sleep(1500);
  }
  throw new Error('スライドの作成が時間内に終わりませんでした。');
};
