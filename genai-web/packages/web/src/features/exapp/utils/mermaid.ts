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

/** Mermaid コードを SVG 文字列へ描画する（補正込み）。 */
export const renderMermaidToSvg = async (code: string): Promise<string> => {
  ensureInitialized();
  const { svg } = await mermaid.render(`m-${newId()}`, correctMermaidCode(code));
  return svg;
};

/** SVG 文字列の描画サイズ（px）を width/height 属性または viewBox から推定する。 */
const svgSize = (svgEl: SVGSVGElement): { width: number; height: number } => {
  const parseLen = (v: string | null): number => {
    if (!v) return 0;
    const n = parseFloat(v.replace(/px$/, ''));
    return Number.isFinite(n) ? n : 0;
  };
  let width = parseLen(svgEl.getAttribute('width'));
  let height = parseLen(svgEl.getAttribute('height'));
  const viewBox = svgEl.getAttribute('viewBox');
  if ((!width || !height) && viewBox) {
    const parts = viewBox.split(/[\s,]+/).map(Number);
    if (parts.length === 4) {
      width = width || parts[2];
      height = height || parts[3];
    }
  }
  return { width: width || 800, height: height || 600 };
};

/**
 * Mermaid コードを PNG の data URL（`data:image/png;base64,...`）へ変換する。
 * Word 等への埋め込み用にラスタライズする。ブラウザ環境でのみ動作する。
 */
export const mermaidToPngDataUrl = async (code: string, scale = 2): Promise<string> => {
  const svg = await renderMermaidToSvg(code);
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
  const svgEl = doc.querySelector('svg');
  if (!svgEl) {
    throw new Error('Mermaid の SVG 生成に失敗しました。');
  }
  const { width, height } = svgSize(svgEl as unknown as SVGSVGElement);
  // ラスタライズ時にサイズが確定するよう明示的に width/height を設定する。
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

  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Canvas コンテキストを取得できませんでした。');
  }
  // 透過だと Word で背景が黒くなることがあるため白で塗る。
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/png');
};
