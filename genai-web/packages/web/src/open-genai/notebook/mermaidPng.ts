import mermaid from 'mermaid';

/** Mermaid を PNG の base64 にする。失敗したら空文字。 */
export const mermaidToPngBase64 = async (code: string): Promise<string> => {
  const trimmed = code.trim();
  if (!trimmed) return '';
  try {
    const { svg } = await mermaid.render(`notebook-diagram-${Date.now()}`, trimmed);
    const parser = new DOMParser();
    const svgElement = parser.parseFromString(svg, 'image/svg+xml').querySelector('svg');
    if (!(svgElement instanceof SVGSVGElement)) return '';
    const viewBox = svgElement.getAttribute('viewBox')?.split(' ').map(Number) || [0, 0, 0, 0];
    const width = Math.max(svgElement.width.baseVal.value || 0, viewBox[2], 1);
    const height = Math.max(svgElement.height.baseVal.value || 0, viewBox[3], 1);
    const scale = 2;
    const canvas = document.createElement('canvas');
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext('2d');
    if (!ctx) return '';
    const wrapped = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="white"/>${svg}</svg>`;
    const img = new Image();
    img.src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(wrapped)))}`;
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error('png'));
    });
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, width, height);
    const url = canvas.toDataURL('image/png');
    const comma = url.indexOf(',');
    return comma >= 0 ? url.slice(comma + 1) : '';
  } catch {
    return '';
  }
};
