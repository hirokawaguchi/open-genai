export const STORAGE_KEY = 'open-genai.shimen.v1';
export const MAX_IMAGE_EDGE = 1280;
export const PLACE_IMAGE_EDGE = 480;
export const HISTORY_LIMIT = 30;
export const MAX_BOARDS = 20;
export const MAX_UPLOADS = 12;
export const MIN_ELEMENT = 16;
export const VISIBLE_EDGE = 24;

export const SIZES = {
  portrait: { label: '縦長', width: 1080, height: 1350 },
  landscape: { label: '横長', width: 1920, height: 1080 },
  square: { label: '正方形', width: 1080, height: 1080 },
} as const;

export type SizeId = keyof typeof SIZES;

export const TEXT_PRESETS = {
  heading: { label: '見出し', text: '見出しを追加', fontSize: 72, bold: true, w: 640 },
  subhead: { label: '小見出し', text: '小見出しを追加', fontSize: 40, bold: true, w: 520 },
  body: { label: '本文', text: '本文を追加', fontSize: 28, bold: false, w: 480 },
} as const;

export type TextPreset = keyof typeof TEXT_PRESETS;
export type Align = 'left' | 'center' | 'right';
export type Handle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';

export const HANDLES: Handle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

export type Box = { x: number; y: number; w: number; h: number };

export type TextElement = Box & {
  id: string;
  kind: 'text';
  text: string;
  fontSize: number;
  color: string;
  bold: boolean;
  align: Align;
};

export type ShapeElement = Box & {
  id: string;
  kind: 'rect' | 'ellipse';
  fill: string;
};

export type ImageElement = Box & {
  id: string;
  kind: 'image';
  src: string;
};

export type Element = TextElement | ShapeElement | ImageElement;

export type Board = {
  id: string;
  title: string;
  size: SizeId;
  background: string;
  elements: Element[];
};

export type Library = {
  version: 1;
  boards: Board[];
  activeId: string;
  uploads: string[];
};

export type HistoryState = {
  past: Board[];
  present: Board;
  future: Board[];
};

export type DropItem =
  | { type: 'rect' }
  | { type: 'ellipse' }
  | { type: 'text'; preset: TextPreset }
  | { type: 'upload'; index: number };

export type ActiveDrag =
  | { kind: 'move'; id: string; dx: number; dy: number }
  | { kind: 'resize'; id: string; handle: Handle; dx: number; dy: number };

const SIZE_IDS = new Set<string>(Object.keys(SIZES));

export const createId = (): string => {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) {
    return uuid;
  }
  return `shimen-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const boardPixelSize = (board: Pick<Board, 'size'>): { width: number; height: number } => {
  const size = SIZES[board.size];
  return { width: size.width, height: size.height };
};

export const fittedSize = (
  width: number,
  height: number,
  maxEdge = MAX_IMAGE_EDGE,
): { width: number; height: number } => {
  const safeW = Math.max(1, width);
  const safeH = Math.max(1, height);
  const edge = Math.max(safeW, safeH);
  if (edge <= maxEdge) {
    return { width: Math.round(safeW), height: Math.round(safeH) };
  }
  const scale = maxEdge / edge;
  return {
    width: Math.max(1, Math.round(safeW * scale)),
    height: Math.max(1, Math.round(safeH * scale)),
  };
};

export const centeredBox = (
  bounds: { width: number; height: number },
  w: number,
  h: number,
): { x: number; y: number } => ({
  x: Math.round((bounds.width - w) / 2),
  y: Math.round((bounds.height - h) / 2),
});

export const clampBox = (bounds: { width: number; height: number }, box: Box): Box => {
  const w = Math.max(MIN_ELEMENT, box.w);
  const h = Math.max(MIN_ELEMENT, box.h);
  let x = box.x;
  let y = box.y;
  if (x + w < VISIBLE_EDGE) {
    x = VISIBLE_EDGE - w;
  }
  if (y + h < VISIBLE_EDGE) {
    y = VISIBLE_EDGE - h;
  }
  if (x > bounds.width - VISIBLE_EDGE) {
    x = bounds.width - VISIBLE_EDGE;
  }
  if (y > bounds.height - VISIBLE_EDGE) {
    y = bounds.height - VISIBLE_EDGE;
  }
  return { x, y, w, h };
};

export const createBoard = (size: SizeId = 'portrait', id = createId()): Board => ({
  id,
  title: '無題の紙面',
  size,
  background: '#ffffff',
  elements: [],
});

export const emptyLibrary = (): Library => {
  const board = createBoard();
  return { version: 1, boards: [board], activeId: board.id, uploads: [] };
};

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const parseElement = (raw: unknown): Element | null => {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const item = raw as Element;
  if (typeof item.id !== 'string' || !item.id) {
    return null;
  }
  if (
    !isFiniteNumber(item.x) ||
    !isFiniteNumber(item.y) ||
    !isFiniteNumber(item.w) ||
    !isFiniteNumber(item.h)
  ) {
    return null;
  }
  if (item.kind === 'text') {
    if (typeof item.text !== 'string') {
      return null;
    }
    return {
      ...item,
      text: item.text,
      fontSize: isFiniteNumber(item.fontSize) ? item.fontSize : 28,
      color: typeof item.color === 'string' ? item.color : '#1a1a1a',
      bold: item.bold === true,
      align: item.align === 'center' || item.align === 'right' ? item.align : 'left',
    };
  }
  if (item.kind === 'rect' || item.kind === 'ellipse') {
    return { ...item, fill: typeof item.fill === 'string' ? item.fill : '#d9e2ec' };
  }
  if (item.kind === 'image' && typeof item.src === 'string' && item.src.startsWith('data:image/')) {
    return item;
  }
  return null;
};

const parseBoard = (raw: unknown): Board | null => {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const item = raw as Board;
  if (typeof item.id !== 'string' || !SIZE_IDS.has(item.size) || !Array.isArray(item.elements)) {
    return null;
  }
  return {
    id: item.id,
    title:
      typeof item.title === 'string' && item.title.trim() ? item.title.slice(0, 80) : '無題の紙面',
    size: item.size,
    background: typeof item.background === 'string' ? item.background : '#ffffff',
    elements: item.elements
      .map(parseElement)
      .filter((element): element is Element => element !== null),
  };
};

export const parseLibrary = (raw: string | null): Library => {
  if (!raw) {
    return emptyLibrary();
  }
  try {
    const data = JSON.parse(raw) as Partial<Library>;
    const boards = Array.isArray(data.boards)
      ? data.boards
          .map(parseBoard)
          .filter((board): board is Board => board !== null)
          .slice(0, MAX_BOARDS)
      : [];
    if (boards.length === 0) {
      return emptyLibrary();
    }
    const activeId = boards.some((board) => board.id === data.activeId)
      ? String(data.activeId)
      : boards[0].id;
    const uploads = Array.isArray(data.uploads)
      ? data.uploads
          .filter(
            (item): item is string => typeof item === 'string' && item.startsWith('data:image/'),
          )
          .slice(0, MAX_UPLOADS)
      : [];
    return { version: 1, boards, activeId, uploads };
  } catch {
    return emptyLibrary();
  }
};

export const textElement = (preset: TextPreset, board: Board, id = createId()): TextElement => {
  const spec = TEXT_PRESETS[preset];
  const h = Math.round(spec.fontSize * 1.6);
  const at = centeredBox(boardPixelSize(board), spec.w, h);
  return {
    id,
    kind: 'text',
    ...at,
    w: spec.w,
    h,
    text: spec.text,
    fontSize: spec.fontSize,
    color: '#1a1a1a',
    bold: spec.bold,
    align: 'left',
  };
};

export const shapeElement = (
  kind: 'rect' | 'ellipse',
  board: Board,
  id = createId(),
): ShapeElement => {
  const w = 280;
  const h = 180;
  const at = centeredBox(boardPixelSize(board), w, h);
  return {
    id,
    kind,
    ...at,
    w,
    h,
    fill: kind === 'rect' ? '#d9e2ec' : '#f3d6b0',
  };
};

export const imageElement = (
  src: string,
  pixelW: number,
  pixelH: number,
  board: Board,
  id = createId(),
): ImageElement => {
  const fit = fittedSize(pixelW, pixelH, PLACE_IMAGE_EDGE);
  const at = centeredBox(boardPixelSize(board), fit.width, fit.height);
  return { id, kind: 'image', ...at, w: fit.width, h: fit.height, src };
};

export const placeElement = (
  board: Board,
  element: Element,
  at?: { x: number; y: number },
): Board => {
  const bounds = boardPixelSize(board);
  const box = at
    ? clampBox(bounds, { ...element, x: at.x - element.w / 2, y: at.y - element.h / 2 })
    : clampBox(bounds, element);
  return { ...board, elements: [...board.elements, { ...element, ...box }] };
};

export const patchElement = (board: Board, id: string, patch: Partial<Element>): Board => ({
  ...board,
  elements: board.elements.map((element) =>
    element.id === id
      ? ({ ...element, ...patch, id: element.id, kind: element.kind } as Element)
      : element,
  ),
});

export const removeElement = (board: Board, id: string): Board => ({
  ...board,
  elements: board.elements.filter((element) => element.id !== id),
});

export const bring = (board: Board, id: string, where: 'front' | 'back'): Board => {
  const element = board.elements.find((item) => item.id === id);
  if (!element) {
    return board;
  }
  const rest = board.elements.filter((item) => item.id !== id);
  return { ...board, elements: where === 'front' ? [...rest, element] : [element, ...rest] };
};

export const nudge = (board: Board, id: string, dx: number, dy: number): Board => {
  const element = board.elements.find((item) => item.id === id);
  if (!element) {
    return board;
  }
  const box = clampBox(boardPixelSize(board), { ...element, x: element.x + dx, y: element.y + dy });
  return patchElement(board, id, box);
};

export const changeSize = (board: Board, size: SizeId): Board => {
  const next = { ...board, size };
  const bounds = boardPixelSize(next);
  return {
    ...next,
    elements: next.elements.map((element) => ({ ...element, ...clampBox(bounds, element) })),
  };
};

const resizeRaw = (box: Box, handle: Handle, dx: number, dy: number): Box => {
  let { x, y, w, h } = box;
  if (handle.includes('e')) {
    w = box.w + dx;
  }
  if (handle.includes('s')) {
    h = box.h + dy;
  }
  if (handle.includes('w')) {
    x = box.x + dx;
    w = box.w - dx;
  }
  if (handle.includes('n')) {
    y = box.y + dy;
    h = box.h - dy;
  }
  if (w < 0) {
    x += w;
    w = -w;
  }
  if (h < 0) {
    y += h;
    h = -h;
  }
  return { x, y, w: Math.max(MIN_ELEMENT, w), h: Math.max(MIN_ELEMENT, h) };
};

export const applyDrag = (board: Board, drag: ActiveDrag): Board => {
  const element = board.elements.find((item) => item.id === drag.id);
  if (!element) {
    return board;
  }
  const bounds = boardPixelSize(board);
  const box =
    drag.kind === 'move'
      ? clampBox(bounds, { ...element, x: element.x + drag.dx, y: element.y + drag.dy })
      : clampBox(bounds, resizeRaw(element, drag.handle, drag.dx, drag.dy));
  return patchElement(board, drag.id, box);
};

export const sameBoard = (a: Board, b: Board): boolean => JSON.stringify(a) === JSON.stringify(b);

export const historyOf = (board: Board): HistoryState => ({ past: [], present: board, future: [] });

export const record = (state: HistoryState, next: Board): HistoryState => {
  if (sameBoard(state.present, next)) {
    return state;
  }
  return {
    past: [...state.past, state.present].slice(-HISTORY_LIMIT),
    present: next,
    future: [],
  };
};

export const replacePresent = (state: HistoryState, next: Board): HistoryState => ({
  ...state,
  present: next,
});

export const undo = (state: HistoryState): HistoryState => {
  const previous = state.past[state.past.length - 1];
  if (!previous) {
    return state;
  }
  return {
    past: state.past.slice(0, -1),
    present: previous,
    future: [state.present, ...state.future].slice(0, HISTORY_LIMIT),
  };
};

export const redo = (state: HistoryState): HistoryState => {
  const next = state.future[0];
  if (!next) {
    return state;
  }
  return {
    past: [...state.past, state.present].slice(-HISTORY_LIMIT),
    present: next,
    future: state.future.slice(1),
  };
};

export const wrapLines = (
  text: string,
  maxWidth: number,
  measure: (line: string) => number,
): string[] => {
  const out: string[] = [];
  for (const paragraph of text.split('\n')) {
    if (!paragraph) {
      out.push('');
      continue;
    }
    let line = '';
    for (const ch of paragraph) {
      const next = line + ch;
      if (line && measure(next) > maxWidth) {
        out.push(line);
        line = ch.trim() ? ch : '';
      } else {
        line = next;
      }
    }
    out.push(line);
  }
  return out.length > 0 ? out : [''];
};

export const addUpload = (library: Library, src: string): Library => {
  const uploads = [src, ...library.uploads.filter((item) => item !== src)].slice(0, MAX_UPLOADS);
  return { ...library, uploads };
};
