import mermaid, { type MermaidConfig } from 'mermaid';
import { useCallback, useEffect, useState } from 'react';
import { correctMermaidCode } from '@/features/exapp/utils/mermaid';
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
      const correctedCode = correctMermaidCode(code);

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
