import {
  type ButtonHTMLAttributes,
  type CSSProperties,
  type DragEvent as ReactDragEvent,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  PiArrowClockwise,
  PiArrowCounterClockwise,
  PiSparkle,
  PiSquareBold,
  PiTextTBold,
  PiUploadSimpleBold,
} from 'react-icons/pi';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { useImageAvailable } from '@/open-genai/image-health/useImageAvailable';
import { errorMessage, generatePlacedImage, rewriteText } from './api';
import { exportBoardPng, readImageFile, shrinkDataUrl } from './draw';
import {
  type ActiveDrag,
  addUpload,
  applyDrag,
  type Board,
  boardPixelSize,
  bring,
  changeSize,
  createBoard,
  type DropItem,
  type Element,
  HANDLES,
  type Handle,
  type HistoryState,
  historyOf,
  imageElement,
  type Library,
  MAX_BOARDS,
  MAX_IMAGE_EDGE,
  nudge,
  parseLibrary,
  placeElement,
  record,
  redo,
  removeElement,
  replacePresent,
  SIZES,
  type SizeId,
  STORAGE_KEY,
  sameBoard,
  shapeElement,
  TEXT_PRESETS,
  type TextPreset,
  textElement,
  undo,
} from './model';

type PanelId = 'shapes' | 'text' | 'uploads' | 'generate';

type DragSession = {
  origin: Board;
  startX: number;
  startY: number;
  drag: { kind: 'move'; id: string } | { kind: 'resize'; id: string; handle: Handle };
};

const COLORS = ['#1a1a1a', '#ffffff', '#d9e2ec', '#f3d6b0', '#1d4e89', '#166534', '#9f1239'];

const clientToBoard = (
  clientX: number,
  clientY: number,
  stage: HTMLElement,
  board: Board,
): { x: number; y: number } => {
  const rect = stage.getBoundingClientRect();
  const size = boardPixelSize(board);
  if (rect.width <= 0 || rect.height <= 0) {
    return { x: 0, y: 0 };
  }
  return {
    x: ((clientX - rect.left) / rect.width) * size.width,
    y: ((clientY - rect.top) / rect.height) * size.height,
  };
};

const handleStyle = (handle: Handle, zoom: number): CSSProperties => {
  const across = handle.includes('w') ? '0%' : handle.includes('e') ? '100%' : '50%';
  const down = handle.includes('n') ? '0%' : handle.includes('s') ? '100%' : '50%';
  return {
    left: across,
    top: down,
    transform: `translate(-50%, -50%) scale(${1 / zoom})`,
  };
};

export const ShimenPage = () => {
  const imageAvailable = useImageAvailable();
  const [library, setLibrary] = useState<Library>(() =>
    parseLibrary(localStorage.getItem(STORAGE_KEY)),
  );
  const active = library.boards.find((board) => board.id === library.activeId) ?? library.boards[0];
  const [history, setHistory] = useState<HistoryState>(() => historyOf(active));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [panel, setPanel] = useState<PanelId | null>('text');
  const [docsOpen, setDocsOpen] = useState(false);
  const [titleEditing, setTitleEditing] = useState(false);
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [zoom, setZoom] = useState(0.4);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragSession | null>(null);
  const titleBefore = useRef(active.title);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const board = history.present;
  const selected = board.elements.find((element) => element.id === selectedId) ?? null;

  useEffect(() => {
    setLibrary((lib) => {
      if (lib.activeId !== history.present.id) {
        return lib;
      }
      const current = lib.boards.find((item) => item.id === history.present.id);
      if (!current || sameBoard(current, history.present)) {
        return lib;
      }
      return {
        ...lib,
        boards: lib.boards.map((item) => (item.id === history.present.id ? history.present : item)),
      };
    });
  }, [history]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(library));
      } catch {
        setNotice('このブラウザの保存容量を超えたので、保存できません。');
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [library]);

  const fit = useCallback(() => {
    const view = viewportRef.current;
    if (!view) {
      return;
    }
    const pixel = SIZES[board.size];
    const next = Math.min(
      (view.clientWidth - 48) / pixel.width,
      (view.clientHeight - 80) / pixel.height,
    );
    setZoom(Math.max(0.1, Math.min(2, next)));
  }, [board.size]);

  useEffect(() => {
    fit();
  }, [fit, board.id]);

  useEffect(() => {
    if (titleEditing) {
      titleInputRef.current?.focus();
    }
  }, [titleEditing]);

  const commit = (next: Board) => {
    setHistory((state) => record(state, next));
  };

  useEffect(() => {
    const move = (event: globalThis.PointerEvent) => {
      const session = dragRef.current;
      const stage = stageRef.current;
      if (!session || !stage) {
        return;
      }
      const point = clientToBoard(event.clientX, event.clientY, stage, session.origin);
      const drag: ActiveDrag = {
        ...session.drag,
        dx: point.x - session.startX,
        dy: point.y - session.startY,
      };
      setHistory((state) => replacePresent(state, applyDrag(session.origin, drag)));
    };
    const up = () => {
      const session = dragRef.current;
      if (!session) {
        return;
      }
      dragRef.current = null;
      setHistory((state) => record({ ...state, present: session.origin }, state.present));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest('input, textarea')) {
        return;
      }
      if (editingId) {
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        setHistory((state) => (event.shiftKey ? redo(state) : undo(state)));
        return;
      }
      if (!selectedId) {
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        commit(removeElement(board, selectedId));
        setSelectedId(null);
        return;
      }
      const step = event.shiftKey ? 10 : 1;
      const delta = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      }[event.key];
      if (!delta) {
        return;
      }
      event.preventDefault();
      commit(nudge(board, selectedId, delta[0], delta[1]));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [board, editingId, selectedId]);

  const beginDrag = (event: ReactPointerEvent, drag: DragSession['drag']) => {
    const stage = stageRef.current;
    if (!stage || editingId) {
      return;
    }
    const point = clientToBoard(event.clientX, event.clientY, stage, board);
    dragRef.current = { origin: board, startX: point.x, startY: point.y, drag };
    setSelectedId(drag.id);
  };

  const addAt = (element: Element, at?: { x: number; y: number }) => {
    commit(placeElement(board, element, at));
    setSelectedId(element.id);
    setEditingId(null);
  };

  const placeUpload = async (src: string, at?: { x: number; y: number }) => {
    const image = new Image();
    image.src = src;
    try {
      await image.decode();
    } catch {
      setNotice('画像を読み込めません。');
      return;
    }
    addAt(imageElement(src, image.naturalWidth || 480, image.naturalHeight || 480, board), at);
  };

  const takeFiles = async (files: FileList | null, at?: { x: number; y: number }) => {
    const file = files?.[0];
    if (file?.type.startsWith('image/') !== true) {
      return;
    }
    try {
      const read = await readImageFile(file, MAX_IMAGE_EDGE);
      setLibrary((lib) => addUpload(lib, read.src));
      addAt(imageElement(read.src, read.width, read.height, board), at);
    } catch {
      setNotice('画像を読み込めません。');
    }
  };

  const dropPoint = (event: ReactDragEvent): { x: number; y: number } | undefined => {
    const stage = stageRef.current;
    if (!stage) {
      return undefined;
    }
    return clientToBoard(event.clientX, event.clientY, stage, board);
  };

  const onDrop = (event: ReactDragEvent) => {
    event.preventDefault();
    const at = dropPoint(event);
    if (event.dataTransfer.files?.length) {
      void takeFiles(event.dataTransfer.files, at);
      return;
    }
    const raw = event.dataTransfer.getData('application/x-shimen');
    if (!raw) {
      return;
    }
    let item: DropItem;
    try {
      item = JSON.parse(raw) as DropItem;
    } catch {
      return;
    }
    if (item.type === 'rect' || item.type === 'ellipse') {
      addAt(shapeElement(item.type, board), at);
      return;
    }
    if (item.type === 'text') {
      addAt(textElement(item.preset, board), at);
      return;
    }
    const src = library.uploads[item.index];
    if (src) {
      void placeUpload(src, at);
    }
  };

  const runRewrite = async () => {
    if (selected?.kind !== 'text' || !instruction.trim()) {
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const text = await rewriteText(selected.text, instruction.trim());
      if (!text) {
        setNotice('書き換え結果が空でした。');
        return;
      }
      commit({
        ...board,
        elements: board.elements.map((element) =>
          element.id === selected.id && element.kind === 'text' ? { ...element, text } : element,
        ),
      });
      setRewriteOpen(false);
    } catch (error) {
      setNotice(errorMessage(error, '書き換えに失敗しました。'));
    } finally {
      setBusy(false);
    }
  };

  const runImage = async () => {
    if (!imageAvailable || !imagePrompt.trim()) {
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const raw = await generatePlacedImage(imagePrompt.trim());
      const src = await shrinkDataUrl(raw, MAX_IMAGE_EDGE);
      const image = new Image();
      image.src = src;
      await image.decode();
      setLibrary((lib) => addUpload(lib, src));
      addAt(imageElement(src, image.naturalWidth || 480, image.naturalHeight || 480, board));
    } catch (error) {
      setNotice(errorMessage(error, '画像を生成できません。'));
    } finally {
      setBusy(false);
    }
  };

  const openBoard = (id: string) => {
    const next = library.boards.find((item) => item.id === id);
    if (!next) {
      return;
    }
    setHistory(historyOf(next));
    setLibrary((lib) => ({ ...lib, activeId: id }));
    setSelectedId(null);
    setEditingId(null);
    setDocsOpen(false);
  };

  const createNew = () => {
    if (library.boards.length >= MAX_BOARDS) {
      setNotice('紙面は20枚までです。');
      return;
    }
    const next = createBoard();
    setHistory(historyOf(next));
    setLibrary((lib) => ({ ...lib, boards: [next, ...lib.boards], activeId: next.id }));
    setSelectedId(null);
    setDocsOpen(false);
  };

  const removeBoard = () => {
    if (library.boards.length <= 1) {
      return;
    }
    const rest = library.boards.filter((item) => item.id !== board.id);
    const next = rest[0];
    if (!next) {
      return;
    }
    setHistory(historyOf(next));
    setLibrary((lib) => ({ ...lib, boards: rest, activeId: next.id }));
    setSelectedId(null);
    setDocsOpen(false);
  };

  const size = boardPixelSize(board);
  const dragPayload = (item: DropItem) => (event: ReactDragEvent) => {
    event.dataTransfer.setData('application/x-shimen', JSON.stringify(item));
    event.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <>
      <PageTitle title='紙面' />
      <div className='flex h-[calc(100dvh-var(--header-height))] flex-col overflow-hidden bg-solid-gray-100'>
        <div className='flex h-12 flex-none items-center gap-2 border-b border-solid-gray-420 bg-white px-3'>
          <div className='relative'>
            <Button
              type='button'
              variant='text'
              size='xs'
              onClick={() => setDocsOpen((open) => !open)}
            >
              書類
            </Button>
            {docsOpen && (
              <div className='absolute top-9 left-0 z-20 w-56 border border-solid-gray-420 bg-white p-2 shadow'>
                <Button
                  type='button'
                  variant='outline'
                  size='xs'
                  className='w-full'
                  onClick={createNew}
                >
                  新しい紙面
                </Button>
                <ul className='mt-2 max-h-48 overflow-auto'>
                  {library.boards.map((item) => (
                    <li key={item.id}>
                      <button
                        type='button'
                        className='w-full truncate px-2 py-1 text-left text-std-16N-170 hover:bg-solid-gray-100'
                        onClick={() => openBoard(item.id)}
                      >
                        {item.title}
                      </button>
                    </li>
                  ))}
                </ul>
                <Button
                  type='button'
                  variant='text'
                  size='xs'
                  className='mt-1'
                  aria-disabled={library.boards.length <= 1}
                  onClick={removeBoard}
                >
                  この紙面を削除
                </Button>
              </div>
            )}
          </div>
          {titleEditing ? (
            <input
              className='w-48 border border-solid-gray-420 px-2 py-1 text-std-16N-170'
              ref={titleInputRef}
              value={board.title}
              onChange={(event) =>
                setHistory((state) =>
                  replacePresent(state, {
                    ...state.present,
                    title: event.target.value.slice(0, 80),
                  }),
                )
              }
              onFocus={() => {
                titleBefore.current = board.title;
              }}
              onBlur={() => {
                setTitleEditing(false);
                setHistory((state) =>
                  record(
                    { ...state, present: { ...state.present, title: titleBefore.current } },
                    state.present,
                  ),
                );
              }}
            />
          ) : (
            <button
              type='button'
              className='max-w-48 truncate px-2 py-1 text-std-16B-170'
              onClick={() => setTitleEditing(true)}
            >
              {board.title}
            </button>
          )}
          <Button
            type='button'
            variant='text'
            size='xs'
            aria-label='戻る'
            onClick={() => setHistory(undo)}
          >
            <PiArrowCounterClockwise />
          </Button>
          <Button
            type='button'
            variant='text'
            size='xs'
            aria-label='進む'
            onClick={() => setHistory(redo)}
          >
            <PiArrowClockwise />
          </Button>
          <label className='ml-2 text-dns-14N-130 text-solid-gray-800'>
            サイズ
            <select
              className='ml-2 border border-solid-gray-420 bg-white px-2 py-1'
              value={board.size}
              onChange={(event) => commit(changeSize(board, event.target.value as SizeId))}
            >
              {(Object.keys(SIZES) as SizeId[]).map((id) => (
                <option key={id} value={id}>
                  {SIZES[id].label}
                </option>
              ))}
            </select>
          </label>
          {notice && (
            <p className='min-w-0 flex-1 truncate text-dns-14N-130 text-solid-gray-800'>{notice}</p>
          )}
          <Button
            type='button'
            variant='solid-fill'
            size='sm'
            className='ml-auto'
            onClick={() => void exportBoardPng(board)}
          >
            ダウンロード
          </Button>
        </div>

        <div className='flex min-h-0 flex-1'>
          <nav
            className='flex w-20 flex-none flex-col border-r border-solid-gray-420 bg-white'
            aria-label='素材'
          >
            <RailButton
              label='素材'
              pressed={panel === 'shapes'}
              onClick={() => setPanel(panel === 'shapes' ? null : 'shapes')}
            >
              <PiSquareBold className='size-6' />
            </RailButton>
            <RailButton
              label='テキスト'
              pressed={panel === 'text'}
              onClick={() => setPanel(panel === 'text' ? null : 'text')}
            >
              <PiTextTBold className='size-6' />
            </RailButton>
            <RailButton
              label='アップロード'
              pressed={panel === 'uploads'}
              onClick={() => setPanel(panel === 'uploads' ? null : 'uploads')}
            >
              <PiUploadSimpleBold className='size-6' />
            </RailButton>
            <RailButton
              label='生成'
              pressed={panel === 'generate'}
              className='mt-auto'
              onClick={() => setPanel(panel === 'generate' ? null : 'generate')}
            >
              <PiSparkle className='size-6' />
            </RailButton>
          </nav>

          {panel && (
            <aside className='flex w-72 flex-none flex-col gap-3 overflow-auto border-r border-solid-gray-420 bg-white p-3'>
              {panel === 'shapes' && (
                <>
                  <PanelItem
                    label='矩形'
                    draggable
                    onDragStart={dragPayload({ type: 'rect' })}
                    onClick={() => addAt(shapeElement('rect', board))}
                  />
                  <PanelItem
                    label='楕円'
                    draggable
                    onDragStart={dragPayload({ type: 'ellipse' })}
                    onClick={() => addAt(shapeElement('ellipse', board))}
                  />
                </>
              )}
              {panel === 'text' &&
                (Object.keys(TEXT_PRESETS) as TextPreset[]).map((preset) => (
                  <PanelItem
                    key={preset}
                    label={TEXT_PRESETS[preset].label}
                    draggable
                    onDragStart={dragPayload({ type: 'text', preset })}
                    onClick={() => addAt(textElement(preset, board))}
                  />
                ))}
              {panel === 'uploads' && (
                <>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={() => fileRef.current?.click()}
                  >
                    画像を選ぶ
                  </Button>
                  <input
                    ref={fileRef}
                    type='file'
                    accept='image/*'
                    className='hidden'
                    onChange={(event) => {
                      void takeFiles(event.target.files);
                      event.target.value = '';
                    }}
                  />
                  <div className='grid grid-cols-2 gap-2'>
                    {library.uploads.map((src, index) => (
                      <button
                        key={src.slice(0, 48) + index}
                        type='button'
                        draggable
                        onDragStart={dragPayload({ type: 'upload', index })}
                        onClick={() => void placeUpload(src)}
                        className='border border-solid-gray-420'
                      >
                        <img src={src} alt='' className='h-20 w-full object-contain' />
                      </button>
                    ))}
                  </div>
                </>
              )}
              {panel === 'generate' && (
                <>
                  <label className='flex flex-col gap-1 text-dns-14N-130'>
                    選択中の文字への指示
                    <textarea
                      className='min-h-16 border border-solid-gray-420 p-2 text-std-16N-170'
                      value={instruction}
                      onChange={(event) => setInstruction(event.target.value)}
                    />
                  </label>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='sm'
                    aria-disabled={busy || selected?.kind !== 'text' || !instruction.trim()}
                    onClick={() => void runRewrite()}
                  >
                    書き換え
                  </Button>
                  <label className='flex flex-col gap-1 text-dns-14N-130'>
                    置く画像
                    <textarea
                      className='min-h-16 border border-solid-gray-420 p-2 text-std-16N-170'
                      value={imagePrompt}
                      onChange={(event) => setImagePrompt(event.target.value)}
                      disabled={!imageAvailable}
                    />
                  </label>
                  {!imageAvailable && (
                    <p className='text-dns-14N-130 text-solid-gray-800'>
                      画像生成が止まっているので、画像は置けません。
                    </p>
                  )}
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='sm'
                    aria-disabled={!imageAvailable || busy || !imagePrompt.trim()}
                    onClick={() => void runImage()}
                  >
                    画像を置く
                  </Button>
                </>
              )}
            </aside>
          )}

          <div
            ref={viewportRef}
            className='relative min-w-0 flex-1 overflow-auto'
            onDragOver={(event) => event.preventDefault()}
            onDrop={onDrop}
          >
            <div
              className='flex min-h-full min-w-full items-center justify-center p-6'
              onPointerDown={(event) => {
                if (event.target === event.currentTarget) {
                  setSelectedId(null);
                  setEditingId(null);
                  setRewriteOpen(false);
                }
              }}
            >
              <div
                style={{ width: size.width * zoom, height: size.height * zoom }}
                className='relative'
              >
                <div
                  ref={stageRef}
                  className='absolute top-0 left-0 bg-white shadow-2'
                  style={{
                    width: size.width,
                    height: size.height,
                    transform: `scale(${zoom})`,
                    transformOrigin: 'top left',
                    background: board.background,
                  }}
                  onPointerDown={(event) => {
                    if (event.target === event.currentTarget) {
                      setSelectedId(null);
                      setEditingId(null);
                      setRewriteOpen(false);
                    }
                  }}
                >
                  {board.elements.map((element) => (
                    <ElementView
                      key={element.id}
                      element={element}
                      selected={element.id === selectedId}
                      editing={element.id === editingId}
                      zoom={zoom}
                      onPointerDown={(event) => {
                        if (element.id === editingId) {
                          return;
                        }
                        event.stopPropagation();
                        beginDrag(event, { kind: 'move', id: element.id });
                      }}
                      onDoubleClick={() => {
                        if (element.kind === 'text') {
                          setSelectedId(element.id);
                          setEditingId(element.id);
                        }
                      }}
                      onText={(text) =>
                        setHistory((state) =>
                          replacePresent(state, {
                            ...state.present,
                            elements: state.present.elements.map((item) =>
                              item.id === element.id && item.kind === 'text'
                                ? { ...item, text }
                                : item,
                            ),
                          }),
                        )
                      }
                      onTextCommit={(before, text) => {
                        setEditingId(null);
                        setHistory((state) =>
                          record(
                            {
                              ...state,
                              present: {
                                ...state.present,
                                elements: state.present.elements.map((item) =>
                                  item.id === element.id && item.kind === 'text'
                                    ? { ...item, text: before }
                                    : item,
                                ),
                              },
                            },
                            {
                              ...state.present,
                              elements: state.present.elements.map((item) =>
                                item.id === element.id && item.kind === 'text'
                                  ? { ...item, text }
                                  : item,
                              ),
                            },
                          ),
                        );
                      }}
                      onHandle={(event, handle) => {
                        event.stopPropagation();
                        beginDrag(event, { kind: 'resize', id: element.id, handle });
                      }}
                    />
                  ))}
                  {selected && (
                    <SelectionBar
                      element={selected}
                      zoom={zoom}
                      rewriteOpen={rewriteOpen}
                      instruction={instruction}
                      busy={busy}
                      onInstruction={setInstruction}
                      onToggleRewrite={() => setRewriteOpen((open) => !open)}
                      onRewrite={() => void runRewrite()}
                      onPatch={(patch) =>
                        commit({
                          ...board,
                          elements: board.elements.map((item) =>
                            item.id === selected.id
                              ? ({ ...item, ...patch, id: item.id, kind: item.kind } as Element)
                              : item,
                          ),
                        })
                      }
                      onBring={(where) => commit(bring(board, selected.id, where))}
                    />
                  )}
                </div>
              </div>
            </div>
            <div className='absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-8 border border-solid-gray-420 bg-white px-3 py-1'>
              <button
                type='button'
                className='px-2'
                onClick={() => setZoom((value) => Math.max(0.1, value - 0.1))}
                aria-label='縮小'
              >
                −
              </button>
              <input
                type='range'
                min={10}
                max={200}
                value={Math.round(zoom * 100)}
                aria-label='倍率'
                onChange={(event) => setZoom(Number(event.target.value) / 100)}
              />
              <span className='w-12 text-dns-14N-130'>{Math.round(zoom * 100)}%</span>
              <button type='button' className='px-2 text-dns-14N-130' onClick={fit}>
                合わせる
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

const RailButton = ({
  label,
  pressed,
  className,
  onClick,
  children,
}: {
  label: string;
  pressed: boolean;
  className?: string;
  onClick: () => void;
  children: ReactNode;
}) => (
  <button
    type='button'
    aria-pressed={pressed}
    className={`flex flex-col items-center gap-1 px-1 py-3 text-dns-14N-130 ${pressed ? 'bg-solid-gray-100' : ''} ${className ?? ''}`}
    onClick={onClick}
  >
    {children}
    {label}
  </button>
);

const PanelItem = ({
  label,
  ...rest
}: { label: string } & ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button
    type='button'
    className='border border-solid-gray-420 px-3 py-4 text-left text-std-16N-170 hover:bg-solid-gray-100'
    {...rest}
  >
    {label}
  </button>
);

const ElementView = ({
  element,
  selected,
  editing,
  zoom,
  onPointerDown,
  onDoubleClick,
  onText,
  onTextCommit,
  onHandle,
}: {
  element: Element;
  selected: boolean;
  editing: boolean;
  zoom: number;
  onPointerDown: (event: ReactPointerEvent) => void;
  onDoubleClick: () => void;
  onText: (text: string) => void;
  onTextCommit: (before: string, text: string) => void;
  onHandle: (event: ReactPointerEvent, handle: Handle) => void;
}) => {
  const before = useRef(element.kind === 'text' ? element.text : '');
  const areaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (editing) {
      areaRef.current?.focus();
    }
  }, [editing]);
  return (
    <div
      className='absolute'
      style={{ left: element.x, top: element.y, width: element.w, height: element.h }}
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
    >
      {element.kind === 'text' && !editing && (
        <div
          className='h-full w-full overflow-hidden whitespace-pre-wrap break-all'
          style={{
            color: element.color,
            fontSize: element.fontSize,
            fontWeight: element.bold ? 700 : 400,
            lineHeight: 1.3,
            textAlign: element.align,
          }}
        >
          {element.text}
        </div>
      )}
      {element.kind === 'text' && editing && (
        <textarea
          className='h-full w-full resize-none bg-transparent'
          style={{
            color: element.color,
            fontSize: element.fontSize,
            fontWeight: element.bold ? 700 : 400,
            lineHeight: 1.3,
            textAlign: element.align,
          }}
          ref={areaRef}
          value={element.text}
          onPointerDown={(event) => event.stopPropagation()}
          onFocus={() => {
            before.current = element.text;
          }}
          onChange={(event) => onText(event.target.value)}
          onBlur={(event) => onTextCommit(before.current, event.target.value)}
        />
      )}
      {element.kind === 'rect' && (
        <div className='h-full w-full' style={{ background: element.fill }} />
      )}
      {element.kind === 'ellipse' && (
        <div className='h-full w-full rounded-[50%]' style={{ background: element.fill }} />
      )}
      {element.kind === 'image' && (
        <img src={element.src} alt='' draggable={false} className='h-full w-full object-fill' />
      )}
      {selected &&
        HANDLES.map((handle) => (
          <button
            key={handle}
            type='button'
            aria-label='サイズ'
            className='absolute size-2.5 border border-blue-900 bg-white'
            style={handleStyle(handle, zoom)}
            onPointerDown={(event) => onHandle(event, handle)}
          />
        ))}
    </div>
  );
};

const SelectionBar = ({
  element,
  zoom,
  rewriteOpen,
  instruction,
  busy,
  onInstruction,
  onToggleRewrite,
  onRewrite,
  onPatch,
  onBring,
}: {
  element: Element;
  zoom: number;
  rewriteOpen: boolean;
  instruction: string;
  busy: boolean;
  onInstruction: (value: string) => void;
  onToggleRewrite: () => void;
  onRewrite: () => void;
  onPatch: (patch: Partial<Element>) => void;
  onBring: (where: 'front' | 'back') => void;
}) => (
  <div
    className='absolute z-10 flex flex-wrap items-center gap-1 border border-solid-gray-420 bg-white p-1 shadow'
    style={{
      left: element.x,
      top: Math.max(0, element.y - 48 / zoom),
      transform: `scale(${1 / zoom})`,
      transformOrigin: 'bottom left',
    }}
    onPointerDown={(event) => event.stopPropagation()}
  >
    {element.kind === 'text' && (
      <>
        <input
          type='number'
          min={8}
          max={200}
          className='w-16 border border-solid-gray-420 px-1'
          value={element.fontSize}
          aria-label='文字の大きさ'
          onChange={(event) =>
            onPatch({ fontSize: Number(event.target.value) || element.fontSize })
          }
        />
        <Button
          type='button'
          variant={element.bold ? 'solid-fill' : 'outline'}
          size='xs'
          onClick={() => onPatch({ bold: !element.bold })}
        >
          太字
        </Button>
        {(['left', 'center', 'right'] as const).map((align) => (
          <Button
            key={align}
            type='button'
            variant={element.align === align ? 'solid-fill' : 'text'}
            size='xs'
            onClick={() => onPatch({ align })}
          >
            {align === 'left' ? '左' : align === 'center' ? '中央' : '右'}
          </Button>
        ))}
        <Button type='button' variant='outline' size='xs' onClick={onToggleRewrite}>
          書き換え
        </Button>
      </>
    )}
    {element.kind !== 'image' && (
      <input
        type='color'
        aria-label='色'
        value={element.kind === 'text' ? element.color : element.fill}
        onChange={(event) =>
          onPatch(
            element.kind === 'text' ? { color: event.target.value } : { fill: event.target.value },
          )
        }
      />
    )}
    {COLORS.slice(0, element.kind === 'image' ? 0 : 5).map((color) => (
      <button
        key={color}
        type='button'
        aria-label={color}
        className='size-5 border border-solid-gray-420'
        style={{ background: color }}
        onClick={() => onPatch(element.kind === 'text' ? { color } : { fill: color })}
      />
    ))}
    <Button type='button' variant='text' size='xs' onClick={() => onBring('front')}>
      前面
    </Button>
    <Button type='button' variant='text' size='xs' onClick={() => onBring('back')}>
      背面
    </Button>
    {rewriteOpen && element.kind === 'text' && (
      <form
        className='flex items-center gap-1'
        onSubmit={(event) => {
          event.preventDefault();
          onRewrite();
        }}
      >
        <input
          className='w-40 border border-solid-gray-420 px-1'
          value={instruction}
          aria-label='書き換えの指示'
          onChange={(event) => onInstruction(event.target.value)}
        />
        <Button
          type='submit'
          variant='solid-fill'
          size='xs'
          aria-disabled={busy || !instruction.trim()}
        >
          実行
        </Button>
      </form>
    )}
  </div>
);
