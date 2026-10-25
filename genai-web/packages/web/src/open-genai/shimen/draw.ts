import { type Board, boardPixelSize, type TextElement, wrapLines } from './model';

const loadImage = (src: string): Promise<HTMLImageElement> =>
  new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('画像を読み込めません'));
    image.src = src;
  });

const drawText = (ctx: CanvasRenderingContext2D, element: TextElement) => {
  ctx.fillStyle = element.color;
  ctx.font = `${element.bold ? 700 : 400} ${element.fontSize}px sans-serif`;
  ctx.textBaseline = 'top';
  const lines = wrapLines(element.text, element.w, (line) => ctx.measureText(line).width);
  const lineHeight = element.fontSize * 1.3;
  lines.forEach((line, index) => {
    const y = element.y + index * lineHeight;
    if (y > element.y + element.h) {
      return;
    }
    const width = ctx.measureText(line).width;
    let x = element.x;
    if (element.align === 'center') {
      x = element.x + (element.w - width) / 2;
    } else if (element.align === 'right') {
      x = element.x + element.w - width;
    }
    ctx.fillText(line, x, y);
  });
};

export const drawBoard = async (ctx: CanvasRenderingContext2D, board: Board): Promise<void> => {
  const size = boardPixelSize(board);
  ctx.clearRect(0, 0, size.width, size.height);
  ctx.fillStyle = board.background;
  ctx.fillRect(0, 0, size.width, size.height);
  for (const element of board.elements) {
    if (element.kind === 'rect') {
      ctx.fillStyle = element.fill;
      ctx.fillRect(element.x, element.y, element.w, element.h);
    } else if (element.kind === 'ellipse') {
      ctx.fillStyle = element.fill;
      ctx.beginPath();
      ctx.ellipse(
        element.x + element.w / 2,
        element.y + element.h / 2,
        element.w / 2,
        element.h / 2,
        0,
        0,
        Math.PI * 2,
      );
      ctx.fill();
    } else if (element.kind === 'image') {
      try {
        const image = await loadImage(element.src);
        ctx.drawImage(image, element.x, element.y, element.w, element.h);
      } catch {
        // 壊れた画像は書き出しで飛ばす。
      }
    } else if (element.kind === 'text') {
      drawText(ctx, element);
    }
  }
};

export const exportBoardPng = async (board: Board): Promise<void> => {
  const size = boardPixelSize(board);
  const canvas = document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return;
  }
  await drawBoard(ctx, board);
  const link = document.createElement('a');
  const name = board.title.replace(/[\\/:*?"<>|]/g, '').trim() || 'shimen';
  link.href = canvas.toDataURL('image/png');
  link.download = `${name}.png`;
  link.click();
};

export const shrinkDataUrl = async (src: string, maxEdge: number): Promise<string> => {
  const image = await loadImage(src);
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  const edge = Math.max(width, height);
  if (edge <= maxEdge && src.startsWith('data:image/jpeg')) {
    return src;
  }
  const scale = edge > maxEdge ? maxEdge / edge : 1;
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return src;
  }
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85);
};

export const readImageFile = async (
  file: File,
  maxEdge: number,
): Promise<{ src: string; width: number; height: number }> => {
  const raw = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('ファイルを読めません'));
    reader.readAsDataURL(file);
  });
  const src = await shrinkDataUrl(raw, maxEdge);
  const image = await loadImage(src);
  return {
    src,
    width: image.naturalWidth || image.width,
    height: image.naturalHeight || image.height,
  };
};
