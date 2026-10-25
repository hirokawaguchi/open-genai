import { describe, expect, it } from 'vitest';
import {
  applyDrag,
  bring,
  changeSize,
  clampBox,
  createBoard,
  fittedSize,
  historyOf,
  imageElement,
  parseLibrary,
  record,
  redo,
  textElement,
  undo,
  wrapLines,
} from './model';

describe('fittedSize', () => {
  it('長辺が上限を超えると比率を保って縮む', () => {
    expect(fittedSize(2000, 1000, 1280)).toEqual({ width: 1280, height: 640 });
  });

  it('上限以内はそのまま', () => {
    expect(fittedSize(400, 300, 1280)).toEqual({ width: 400, height: 300 });
  });
});

describe('clampBox', () => {
  it('紙の外へ全部出さない', () => {
    const box = clampBox({ width: 1080, height: 1350 }, { x: -400, y: 10, w: 100, h: 40 });
    expect(box.x + box.w).toBeGreaterThanOrEqual(24);
    expect(box.w).toBe(100);
  });
});

describe('elements', () => {
  it('前面へ出すと配列の末尾になる', () => {
    const board = createBoard('square', 'board');
    const first = textElement('heading', board, 'a');
    const second = textElement('body', board, 'b');
    const stacked = { ...board, elements: [first, second] };
    expect(bring(stacked, 'a', 'front').elements.map((element) => element.id)).toEqual(['b', 'a']);
  });

  it('ドラッグで移動し、紙から完全には出ない', () => {
    const board = createBoard('square', 'board');
    const text = textElement('body', board, 'a');
    const placed = { ...board, elements: [{ ...text, x: 0, y: 0 }] };
    const next = applyDrag(placed, { kind: 'move', id: 'a', dx: -500, dy: 0 });
    const moved = next.elements[0];
    expect(moved?.x + (moved?.w ?? 0)).toBeGreaterThanOrEqual(24);
  });

  it('画像は配置用の上限に収まる', () => {
    const board = createBoard('portrait', 'board');
    const image = imageElement('data:image/png;base64,aa', 2000, 1000, board, 'img');
    expect(Math.max(image.w, image.h)).toBeLessThanOrEqual(480);
  });

  it('サイズを変えても要素が紙から消えない', () => {
    const board = createBoard('landscape', 'board');
    const text = { ...textElement('heading', board, 'a'), x: 1800, y: 900 };
    const next = changeSize({ ...board, elements: [text] }, 'square');
    const moved = next.elements[0];
    expect(moved?.x).toBeLessThan(1080);
    expect(moved?.y).toBeLessThan(1080);
  });
});

describe('history', () => {
  it('戻すと直前の紙面に戻る', () => {
    const board = createBoard('portrait', 'board');
    const next = { ...board, title: '改題' };
    const recorded = record(historyOf(board), next);
    expect(undo(recorded).present.title).toBe('無題の紙面');
    expect(redo(undo(recorded)).present.title).toBe('改題');
  });
});

describe('wrapLines', () => {
  it('幅を超えた文字は次の行へ送る', () => {
    expect(wrapLines('abcdef', 3, (line) => line.length)).toEqual(['abc', 'def']);
  });
});

describe('parseLibrary', () => {
  it('壊れた保存データは空の紙面に戻す', () => {
    const library = parseLibrary('{');
    expect(library.boards).toHaveLength(1);
    expect(library.version).toBe(1);
  });

  it('画像以外のアップロードは捨てる', () => {
    const board = createBoard('square', 'board');
    const raw = JSON.stringify({
      version: 1,
      boards: [board],
      activeId: board.id,
      uploads: ['https://example.com/a.png', 'data:image/png;base64,aa'],
    });
    expect(parseLibrary(raw).uploads).toEqual(['data:image/png;base64,aa']);
  });
});
