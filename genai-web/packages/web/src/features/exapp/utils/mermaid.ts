import mermaid, { type MermaidConfig } from 'mermaid';
import { newId } from '@/utils/uuid';

const defaultConfig: MermaidConfig = {
  suppressErrorRendering: true,
  securityLevel: 'antiscript',
  fontFamily: 'monospace',
  fontSize: 16,
  htmlLabels: true,
  theme: 'default',
};

let initialized = false;
const ensureInitialized = () => {
  if (!initialized) {
    mermaid.initialize(defaultConfig);
    initialized = true;
  }
};

/**
 * AI 生成などで崩れがちな Mermaid 記法を描画可能な形へ補正する。
 * プレビュー（MermaidRenderer）と Word 書き出し用の画像化で同じ結果になるよう共有する。
 */
export const correctMermaidCode = (code: string): string =>
  code
    // エスケープされた改行文字を実際の改行に変換
    .replace(/\\n/g, '\n')
    .replace(/・/g, '/')
    .replace(/：/g, ':')
    .replace(/subgraph\s+(.*)/gm, (_, title) => {
      const correctedTitle = title
        .replace(/\[.*?\]/g, '')
        .replace(/,/g, '')
        .replace(/[()（）]/g, '');
      return `subgraph ${correctedTitle}`;
    })
    .replace(/class\s+(\w+)\[.*?\]/gm, (_, className) => `class ${className}`)
    .replace(/\[([^\]]+)\]/g, (match, content) => {
      // 座標表記 [数字, 数字] の場合は変換しない
      if (/^\s*\d+\s*,\s*\d+\s*$/.test(content)) {
        return match;
      }
      const replaced = content.replace(/\(/g, '（').replace(/\)/g, '）');
      return `[${replaced}]`;
    })
    // quadrant chart用: x-axis/y-axisには引用符が必要
    .replace(/(x-axis|y-axis)\s+(.+?)\s+-->\s+(.+?)$/gm, (_, axis, left, right) => {
      const leftLabel = left.trim().replace(/^["']|["']$/g, '');
      const rightLabel = right.trim().replace(/^["']|["']$/g, '');
      return `${axis} "${leftLabel}" --> "${rightLabel}"`;
    })
    // quadrant-Xにも引用符が必要
    .replace(/quadrant-([1-9])\s+(.+?)$/gm, (_, num, label) => {
      const trimmedLabel = label.trim().replace(/^["']|["']$/g, '');
      return `quadrant-${num} "${trimmedLabel}"`;
    })
    // データポイント名には引用符不要、座標値を0-1に正規化
    .replace(
      /^(\s*)([^:\n]+):\s*\[(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\]$/gm,
      (_, indent, name, x, y) => {
        const trimmedName = name.trim().replace(/^["']|["']$/g, '');
        let xVal = parseFloat(x);
        let yVal = parseFloat(y);
        if (xVal > 1) xVal = xVal / 100;
        if (yVal > 1) yVal = yVal / 100;
        return `${indent}${trimmedName}: [${xVal}, ${yVal}]`;
      },
    );

const FLOW_DIR_RE = /^(\s*)(flowchart|graph)(?:\s+(TD|TB|BT|DT|LR|RL))?(\b.*)?$/im;
const OTHER_DIAGRAM_RE =
  /^(sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|mindmap|timeline|gitGraph|journey|quadrantChart|xychart|sankey|block-beta|requirementDiagram|C4Context|architecture-beta)\b/im;

/** flowchart / graph を LR（横書き）にする。他の図種はそのまま。 */
export const mermaidFlowchartLr = (code: string): string => {
  const text = code.trim();
  if (!text || OTHER_DIAGRAM_RE.test(text)) return text;
  return text.replace(FLOW_DIR_RE, (_, indent: string, kind: string, _dir: string, rest: string) => {
    return `${indent}${kind} LR${rest ?? ''}`;
  });
};

/** Mermaid コードを SVG 文字列へ描画する（補正込み）。 */
export const renderMermaidToSvg = async (code: string): Promise<string> => {
  ensureInitialized();
  const { svg } = await mermaid.render(`m-${newId()}`, correctMermaidCode(code));
  return svg;
};

/** 16:9 スライド本文枠（約 12.0in × 4.58in）を 200dpi 相当で焼く。 */
export const SLIDE_MERMAID_PNG = { width: 2400, height: 920, pad: 56 };

const SLIDE_MERMAID_INIT =
  '%%{init: {"flowchart": {"useMaxWidth": false, "nodeSpacing": 56, "rankSpacing": 72}, "themeVariables": {"fontSize": "22px", "fontFamily": "Noto Sans JP, sans-serif"}}}%%\n';

/** スライド用。LR と大きい文字を付けてから描く。 */
export const prepareSlideMermaid = (code: string): string => {
  const body = mermaidFlowchartLr(code).replace(/^\s*%%\{init[\s\S]*?\}%%\s*/i, '');
  return `${SLIDE_MERMAID_INIT}${body}`;
};

/** SVG の実サイズ。width="100%" は無視して viewBox を使う。 */
const svgSize = (svgEl: SVGSVGElement): { width: number; height: number } => {
  const parseLen = (v: string | null): number => {
    if (!v || /%/.test(v)) return 0;
    const n = parseFloat(v.replace(/px$/, ''));
    return Number.isFinite(n) && n > 0 ? n : 0;
  };
  const viewBox = svgEl.getAttribute('viewBox');
  let vbW = 0;
  let vbH = 0;
  if (viewBox) {
    const parts = viewBox.split(/[\s,]+/).map(Number);
    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
      vbW = parts[2];
      vbH = parts[3];
    }
  }
  const width = parseLen(svgEl.getAttribute('width')) || vbW;
  const height = parseLen(svgEl.getAttribute('height')) || vbH;
  return { width: width || 800, height: height || 600 };
};

const loadSvgImage = async (svgEl: Element, width: number, height: number): Promise<HTMLImageElement> => {
  svgEl.setAttribute('width', String(width));
  svgEl.setAttribute('height', String(height));
  const serialized = new XMLSerializer().serializeToString(svgEl);
  const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(serialized)}`;
  const img = new Image();
  img.width = width;
  img.height = height;
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error('Mermaid 画像の読み込みに失敗しました。'));
    img.src = svgUrl;
  });
  return img;
};

const toPngDataUrl = (canvas: HTMLCanvasElement): string => canvas.toDataURL('image/png');

/**
 * Mermaid コードを PNG の data URL（`data:image/png;base64,...`）へ変換する。
 * Word 等への埋め込み用にラスタライズする。ブラウザ環境でのみ動作する。
 * `landscape: true` のときはスライド本文枠の横長・高解像度で焼く。
 */
export const mermaidToPngDataUrl = async (
  code: string,
  scale = 2,
  options?: { landscape?: boolean },
): Promise<string> => {
  const svg = await renderMermaidToSvg(options?.landscape ? prepareSlideMermaid(code) : code);
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
  const svgEl = doc.querySelector('svg');
  if (!svgEl) {
    throw new Error('Mermaid の SVG 生成に失敗しました。');
  }
  const { width: srcW, height: srcH } = svgSize(svgEl as unknown as SVGSVGElement);

  if (options?.landscape) {
    const { width: cw, height: ch, pad } = SLIDE_MERMAID_PNG;
    const innerW = cw - pad * 2;
    const innerH = ch - pad * 2;
    const fit = Math.min(innerW / srcW, innerH / srcH);
    const dw = Math.max(1, Math.round(srcW * fit));
    const dh = Math.max(1, Math.round(srcH * fit));
    // ベクターを配置サイズでラスタライズする（小さい PNG を引き伸ばさない）。
    const img = await loadSvgImage(svgEl, dw, dh);
    const canvas = document.createElement('canvas');
    canvas.width = cw;
    canvas.height = ch;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('Canvas コンテキストを取得できませんでした。');
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, cw, ch);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, Math.round((cw - dw) / 2), Math.round((ch - dh) / 2), dw, dh);
    return toPngDataUrl(canvas);
  }

  const img = await loadSvgImage(svgEl, srcW, srcH);
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(srcW * scale));
  canvas.height = Math.max(1, Math.round(srcH * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Canvas コンテキストを取得できませんでした。');
  }
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return toPngDataUrl(canvas);
};
