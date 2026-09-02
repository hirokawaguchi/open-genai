import mermaid, { type MermaidConfig } from 'mermaid';
import { useCallback, useEffect, useState } from 'react';
import { newId } from '@/utils/uuid';

const defaultConfig: MermaidConfig = {
  suppressErrorRendering: true,
  securityLevel: 'antiscript',
  fontFamily: 'monospace',
  fontSize: 16,
  htmlLabels: true,
  theme: 'default',
};

mermaid.initialize(defaultConfig);

type Props = {
  code: string;
};

export const MermaidRenderer = (props: Props) => {
  const { code } = props;

  const [svgContent, setSvgContent] = useState<string>('');
  const [hasError, setHasError] = useState(false);

  const render = useCallback(async () => {
    if (!code) {
      return;
    }

    try {
      const correctedCode = code
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

            // 値が1より大きい場合は100で割って0-1の範囲に正規化
            if (xVal > 1) xVal = xVal / 100;
            if (yVal > 1) yVal = yVal / 100;

            return `${indent}${trimmedName}: [${xVal}, ${yVal}]`;
          },
        );

      const { svg } = await mermaid.render(`m-${newId()}`, correctedCode);

      // SVG文字列をパースしてDOMオブジェクトに変換
      const parser = new DOMParser();
      const doc = parser.parseFromString(svg, 'image/svg+xml');
      const svgElement = doc.querySelector('svg');

      if (svgElement) {
        // SVG要素に必要な属性を設定
        svgElement.setAttribute('width', '100%');
        svgElement.setAttribute('height', '100%');
        setSvgContent(svgElement.outerHTML);
        setHasError(false);
      }
    } catch (error) {
      setSvgContent(`レンダリングに失敗しました。Mermaid記法に誤りがあります。${error}`);
      setHasError(true);
    }
  }, [code]);

  useEffect(() => {
    render();
  }, [render]);

  if (hasError) {
    return (
      <div className='overflow-hidden rounded-8 border border-error-2 bg-white p-4'>
        <p
          className='whitespace-pre-wrap wrap-break-word text-error-2'
          style={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
        >
          {svgContent}
        </p>
      </div>
    );
  }

  return (
    <div className='flex items-center justify-center rounded-8 border border-solid-gray-420 bg-white p-8'>
      <div
        className='flex h-full w-full items-center justify-center'
        // biome-ignore lint/security/noDangerouslySetInnerHtml: AI generated SVG content
        dangerouslySetInnerHTML={{ __html: svgContent }}
      />
    </div>
  );
};
