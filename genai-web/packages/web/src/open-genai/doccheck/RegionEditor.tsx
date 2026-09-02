import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { newId } from '@/utils/uuid';
import type { DoccheckFieldType, RegionTemplate } from './types';

type DraftRegion = RegionTemplate & { localId: string };

type DragMode =
  | { kind: 'create'; startX: number; startY: number }
  | { kind: 'move'; localId: string; ox: number; oy: number; orig: DraftRegion }
  | {
      kind: 'resize';
      localId: string;
      handle: 'se';
      orig: DraftRegion;
    };

const MAX_DEFAULT = 50;
const MIN_SIZE = 0.01;
const DEFAULT_SPLIT_N = 5;
const DEFAULT_SPLIT_OVERLAP = 0.08;

const FIELD_TYPE_VALUES = [
  'text_single',
  'text_multi',
  'date',
  'number',
  'choice',
  'choice_multi',
] as const;

const normalizeFieldType = (value: unknown): DoccheckFieldType => {
  const v = String(value ?? '').trim();
  if (v === '' || v === 'text') return 'text_single';
  return (FIELD_TYPE_VALUES as readonly string[]).includes(v)
    ? (v as DoccheckFieldType)
    : 'text_single';
};

const isTextType = (t: DoccheckFieldType) => t === 'text_single' || t === 'text_multi';
const isChoiceType = (t: DoccheckFieldType) => t === 'choice' || t === 'choice_multi';

const newLocalId = () => newId();

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

const num = (v: unknown, fallback = 0) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

/** 1 行帯を横に N 分割（隣同士オーバーラップ）。親矩形内にクランプ。 */
export const splitHorizontally = (
  parent: { x: number; y: number; w: number; h: number },
  parts: number,
  overlapRatio: number,
): Array<{ x: number; y: number; w: number; h: number }> => {
  const n = Math.max(2, Math.floor(parts));
  const ol = Math.max(0, Math.min(0.45, overlapRatio));
  const stride = parent.w / n;
  const expand = stride * ol;
  const x0 = parent.x;
  const x1 = parent.x + parent.w;
  const out: Array<{ x: number; y: number; w: number; h: number }> = [];
  for (let i = 0; i < n; i += 1) {
    const left = Math.max(x0, x0 + i * stride - expand);
    const right = Math.min(x1, x0 + (i + 1) * stride + expand);
    out.push({
      x: left,
      y: parent.y,
      w: Math.max(MIN_SIZE, right - left),
      h: parent.h,
    });
  }
  return out;
};

const toDraft = (regions: RegionTemplate[]): DraftRegion[] =>
  regions.map((r, i) => ({
    ...r,
    localId: r.id || newLocalId(),
    name: r.name || `領域${i + 1}`,
    page_index: r.page_index ?? 0,
    x: clamp01(num(r.x)),
    y: clamp01(num(r.y)),
    w: Math.max(MIN_SIZE, num(r.w, MIN_SIZE)),
    h: Math.max(MIN_SIZE, num(r.h, MIN_SIZE)),
    field_type: normalizeFieldType(r.field_type),
    is_handwriting: r.is_handwriting ?? true,
    is_trap: r.is_trap ?? false,
    trap_answer: r.trap_answer ?? '',
    sort_order: r.sort_order ?? i,
    group_id: r.group_id ?? null,
    group_name: r.group_name ?? '',
    line_index: r.line_index ?? 0,
    part_index: r.part_index ?? 0,
    choice_options: r.choice_options ?? [],
  }));

type Props = {
  imageUrl: string | null;
  initialRegions: RegionTemplate[];
  maxRegions?: number;
  disabled?: boolean;
  onChange?: (regions: RegionTemplate[]) => void;
};

/**
 * 見本画像上で OCR クロップ領域（正規化座標）を手動設定する。
 * 座標は常に <img> の表示矩形を基準にする（ラッパー基準だと再表示でずれやすい）。
 */
export const RegionEditor = ({
  imageUrl,
  initialRegions,
  maxRegions = MAX_DEFAULT,
  disabled,
  onChange,
}: Props) => {
  const imgRef = useRef<HTMLImageElement>(null);
  const [imageReady, setImageReady] = useState(false);
  const [regions, setRegions] = useState<DraftRegion[]>(() => toDraft(initialRegions));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drag, setDrag] = useState<DragMode | null>(null);
  const [draftBox, setDraftBox] = useState<{ x: number; y: number; w: number; h: number } | null>(
    null,
  );
  const [splitN, setSplitN] = useState(DEFAULT_SPLIT_N);
  const [splitOverlapPct, setSplitOverlapPct] = useState(Math.round(DEFAULT_SPLIT_OVERLAP * 100));
  const [splitError, setSplitError] = useState<string | null>(null);

  useEffect(() => {
    setImageReady(false);
    const img = imgRef.current;
    if (img?.complete && img.naturalWidth > 0) {
      setImageReady(true);
    }
  }, [imageUrl]);

  const emit = useCallback(
    (next: DraftRegion[]) => {
      setRegions(next);
      onChange?.(
        next.map(({ localId: _lid, ...rest }, i) => ({
          ...rest,
          x: num(rest.x),
          y: num(rest.y),
          w: num(rest.w),
          h: num(rest.h),
          sort_order: i,
        })),
      );
    },
    [onChange],
  );

  const selected = regions.find((r) => r.localId === selectedId) ?? null;
  const selectedFieldType = normalizeFieldType(selected?.field_type);

  const clientToNorm = (clientX: number, clientY: number) => {
    const img = imgRef.current;
    if (!img) return { x: 0, y: 0 };
    const rect = img.getBoundingClientRect();
    return {
      x: clamp01((clientX - rect.left) / Math.max(rect.width, 1)),
      y: clamp01((clientY - rect.top) / Math.max(rect.height, 1)),
    };
  };

  const onPointerDown = (e: ReactPointerEvent) => {
    if (disabled || !imageUrl || !imageReady) return;
    const target = e.target as HTMLElement;
    const handle = target.dataset.handle;
    const regionId = target.dataset.regionId;
    const { x, y } = clientToNorm(e.clientX, e.clientY);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);

    if (handle === 'se' && regionId) {
      const orig = regions.find((r) => r.localId === regionId);
      if (!orig) return;
      setSelectedId(regionId);
      setDrag({ kind: 'resize', localId: regionId, handle: 'se', orig: { ...orig } });
      return;
    }
    if (regionId) {
      const orig = regions.find((r) => r.localId === regionId);
      if (!orig) return;
      setSelectedId(regionId);
      setDrag({
        kind: 'move',
        localId: regionId,
        ox: x - orig.x,
        oy: y - orig.y,
        orig: { ...orig },
      });
      return;
    }
    if (regions.length >= maxRegions) return;
    setSelectedId(null);
    setDrag({ kind: 'create', startX: x, startY: y });
    setDraftBox({ x, y, w: 0, h: 0 });
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    if (!drag) return;
    const { x, y } = clientToNorm(e.clientX, e.clientY);
    if (drag.kind === 'create') {
      const nx = Math.min(drag.startX, x);
      const ny = Math.min(drag.startY, y);
      const w = Math.abs(x - drag.startX);
      const h = Math.abs(y - drag.startY);
      setDraftBox({ x: nx, y: ny, w, h });
      return;
    }
    if (drag.kind === 'move') {
      const w = drag.orig.w;
      const h = drag.orig.h;
      const nx = clamp01(x - drag.ox);
      const ny = clamp01(y - drag.oy);
      setRegions((prev) => {
        const next = prev.map((r) =>
          r.localId === drag.localId
            ? { ...r, x: Math.min(nx, 1 - w), y: Math.min(ny, 1 - h) }
            : r,
        );
        onChange?.(
          next.map(({ localId: _lid, ...rest }, i) => ({
            ...rest,
            x: num(rest.x),
            y: num(rest.y),
            w: num(rest.w),
            h: num(rest.h),
            sort_order: i,
          })),
        );
        return next;
      });
      return;
    }
    if (drag.kind === 'resize') {
      const nx = Math.max(drag.orig.x + MIN_SIZE, x);
      const ny = Math.max(drag.orig.y + MIN_SIZE, y);
      setRegions((prev) => {
        const next = prev.map((r) =>
          r.localId === drag.localId
            ? {
                ...r,
                w: clamp01(nx - drag.orig.x),
                h: clamp01(ny - drag.orig.y),
              }
            : r,
        );
        onChange?.(
          next.map(({ localId: _lid, ...rest }, i) => ({
            ...rest,
            x: num(rest.x),
            y: num(rest.y),
            w: num(rest.w),
            h: num(rest.h),
            sort_order: i,
          })),
        );
        return next;
      });
    }
  };

  const onPointerUp = () => {
    if (drag?.kind === 'create' && draftBox && draftBox.w >= MIN_SIZE && draftBox.h >= MIN_SIZE) {
      const localId = newLocalId();
      const box = draftBox;
      setRegions((prev) => {
        const next: DraftRegion[] = [
          ...prev,
          {
            localId,
            name: `領域${prev.length + 1}`,
            page_index: 0,
            x: box.x,
            y: box.y,
            w: box.w,
            h: box.h,
            field_type: 'text_single',
            is_handwriting: true,
            is_trap: false,
            trap_answer: '',
            sort_order: prev.length,
            group_id: null,
            group_name: '',
            line_index: 0,
            part_index: 0,
            choice_options: [],
          },
        ];
        onChange?.(
          next.map(({ localId: _lid, ...rest }, i) => ({
            ...rest,
            x: num(rest.x),
            y: num(rest.y),
            w: num(rest.w),
            h: num(rest.h),
            sort_order: i,
          })),
        );
        return next;
      });
      setSelectedId(localId);
    }
    setDrag(null);
    setDraftBox(null);
  };

  const updateSelected = (patch: Partial<DraftRegion>) => {
    if (!selectedId) return;
    emit(regions.map((r) => (r.localId === selectedId ? { ...r, ...patch } : r)));
  };

  const removeSelected = () => {
    if (!selectedId) return;
    emit(regions.filter((r) => r.localId !== selectedId));
    setSelectedId(null);
  };

  const splitSelectedHorizontally = () => {
    if (!selected || selected.is_trap || disabled) return;
    const n = Math.max(2, Math.min(20, Math.floor(splitN) || DEFAULT_SPLIT_N));
    const extra = n - 1;
    if (regions.length + extra > maxRegions) {
      setSplitError(`分割後に上限（${maxRegions}）を超えます`);
      return;
    }
    const overlap = Math.max(0, Math.min(45, splitOverlapPct)) / 100;
    const boxes = splitHorizontally(selected, n, overlap);
    const multi = selectedFieldType === 'text_multi';
    // 単一行分割: 同時生成の安定 group_id で束ねる（項目名が偶然一致しても混ざらない）。
    // 複数行分割: group_id を付けず、出力項目名で行をまたいで束ねる。
    const groupId = multi ? null : selected.group_id || newLocalId();
    const groupName = (selected.group_name || selected.name || '項目').trim();
    const lineIndex = selected.line_index ?? 0;
    const pieces: DraftRegion[] = boxes.map((box, i) => ({
      ...selected,
      localId: newLocalId(),
      id: undefined,
      name: multi
        ? `${groupName}-L${lineIndex + 1}-P${i + 1}`
        : `${groupName}-P${i + 1}`,
      x: box.x,
      y: box.y,
      w: box.w,
      h: box.h,
      group_id: groupId,
      group_name: groupName,
      line_index: lineIndex,
      part_index: i,
      is_trap: false,
      trap_answer: '',
    }));
    const idx = regions.findIndex((r) => r.localId === selected.localId);
    const next = [...regions.slice(0, idx), ...pieces, ...regions.slice(idx + 1)];
    setSplitError(null);
    emit(next);
    setSelectedId(pieces[0]?.localId ?? null);
  };

  return (
    <div className='grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]'>
      <div className='flex flex-col gap-2'>
        <p className='text-std-14N-170 text-solid-gray-700'>
          見本画像上をドラッグして領域を追加（{regions.length}/{maxRegions}）。
          長い1行は選択して横N分割できます。複数行は行ごとに枠を作り、同じ出力項目名と行番号を付けてください（出力時に結合）。
          クロップ余白のオーバーラップはサーバが自動付与します。
        </p>
        <div className='max-h-[70vh] w-full overflow-auto rounded-8 border border-solid-gray-420 bg-solid-gray-50'>
          <div
            className='relative w-full leading-none select-none touch-none'
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            {imageUrl ? (
              <img
                ref={imgRef}
                src={imageUrl}
                alt='帳票見本'
                draggable={false}
                className='pointer-events-none block h-auto w-full max-w-full'
                onLoad={() => setImageReady(true)}
              />
            ) : (
              <div className='flex min-h-64 items-center justify-center p-8 text-solid-gray-700 leading-normal'>
                見本画像をアップロードしてください
              </div>
            )}
            {imageReady &&
              regions.map((r) => {
                const active = r.localId === selectedId;
                return (
                  <div
                    key={r.localId}
                    data-region-id={r.localId}
                    className={`absolute box-border border-2 ${
                      active
                        ? 'border-blue-900 bg-blue-900/15'
                        : r.is_trap
                          ? 'border-orange-700 bg-orange-700/10'
                          : 'border-green-800 bg-green-800/10'
                    }`}
                    style={{
                      left: `${r.x * 100}%`,
                      top: `${r.y * 100}%`,
                      width: `${r.w * 100}%`,
                      height: `${r.h * 100}%`,
                    }}
                  >
                    <span className='pointer-events-none absolute left-0 top-0 max-w-full truncate bg-white/90 px-1 text-std-12N-170 leading-normal'>
                      {r.name}
                    </span>
                    {active && (
                      <span
                        data-region-id={r.localId}
                        data-handle='se'
                        className='absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-se-resize rounded-2 border border-white bg-blue-900'
                      />
                    )}
                  </div>
                );
              })}
            {draftBox && (
              <div
                className='pointer-events-none absolute border-2 border-dashed border-blue-900 bg-blue-900/10'
                style={{
                  left: `${draftBox.x * 100}%`,
                  top: `${draftBox.y * 100}%`,
                  width: `${draftBox.w * 100}%`,
                  height: `${draftBox.h * 100}%`,
                }}
              />
            )}
          </div>
        </div>
        {imageUrl && !imageReady && (
          <p className='text-std-14N-170 text-solid-gray-700'>見本画像を読み込み中…</p>
        )}
      </div>

      <div className='flex flex-col gap-3'>
        <div>
          <h3 className='text-std-16B-150'>領域一覧</h3>
          <ul className='mt-2 max-h-48 space-y-1 overflow-auto'>
            {regions.map((r, i) => (
              <li key={r.localId}>
                <button
                  type='button'
                  className={`w-full rounded-8 px-2 py-1.5 text-left text-std-14N-170 ${
                    r.localId === selectedId
                      ? 'bg-blue-50 text-blue-900'
                      : 'hover:bg-solid-gray-50'
                  }`}
                  onClick={() => setSelectedId(r.localId)}
                >
                  {i + 1}. {r.name}
                  {r.is_trap ? '（トラップ）' : ''}
                  {r.group_name ? ` →${r.group_name}` : ''}
                </button>
              </li>
            ))}
            {regions.length === 0 && (
              <li className='text-std-14N-170 text-solid-gray-700'>まだ領域がありません</li>
            )}
          </ul>
        </div>

        {selected && (
          <div className='flex flex-col gap-2 border-t border-solid-gray-420 pt-3'>
            <h3 className='text-std-16B-150'>選択中の領域</h3>
            <Label htmlFor='re-name' size='sm'>
              名前
            </Label>
            <input
              id='re-name'
              className='w-full rounded-8 border border-solid-gray-420 px-3 py-2'
              value={selected.name}
              disabled={disabled}
              onChange={(e) => updateSelected({ name: e.target.value })}
            />
            <Label htmlFor='re-type' size='sm'>
              種別
            </Label>
            <select
              id='re-type'
              className='w-full rounded-8 border border-solid-gray-420 px-3 py-2'
              value={selectedFieldType}
              disabled={disabled}
              onChange={(e) =>
                updateSelected({ field_type: normalizeFieldType(e.target.value) })
              }
            >
              <option value='text_single'>テキスト（単一行）</option>
              <option value='text_multi'>テキスト（複数行）</option>
              <option value='date'>日付</option>
              <option value='number'>数値</option>
              <option value='choice'>選択（単一）</option>
              <option value='choice_multi'>選択（複数）</option>
            </select>
            <label className='flex items-center gap-2 text-std-14N-170'>
              <input
                type='checkbox'
                checked={!!selected.is_handwriting}
                disabled={disabled}
                onChange={(e) => updateSelected({ is_handwriting: e.target.checked })}
              />
              手書きを想定
            </label>
            <label className='flex items-center gap-2 text-std-14N-170'>
              <input
                type='checkbox'
                checked={!!selected.is_trap}
                disabled={disabled}
                onChange={(e) => updateSelected({ is_trap: e.target.checked })}
              />
              トラップ領域
            </label>
            {selected.is_trap && (
              <>
                <Label htmlFor='re-trap' size='sm'>
                  トラップ正解
                </Label>
                <input
                  id='re-trap'
                  className='w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                  value={selected.trap_answer || ''}
                  disabled={disabled}
                  onChange={(e) => updateSelected({ trap_answer: e.target.value })}
                />
              </>
            )}
            {!selected.is_trap && isTextType(selectedFieldType) && (
              <>
                <Label htmlFor='re-group' size='sm'>
                  {selectedFieldType === 'text_multi'
                    ? '出力項目名（複数行の結合キー）'
                    : '出力項目名（列名・任意）'}
                </Label>
                <input
                  id='re-group'
                  className='w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                  value={selected.group_name || ''}
                  placeholder='例: 住所（空なら領域名で出力）'
                  disabled={disabled}
                  onChange={(e) => updateSelected({ group_name: e.target.value })}
                />
                <p className='text-std-12N-170 text-solid-gray-700'>
                  {selectedFieldType === 'text_multi'
                    ? '複数行は行ごとに枠を作り、同じ出力項目名を付けてください（出力時に改行で結合）。'
                    : selected.group_id
                      ? '横分割グループの列名です（束ねは分割IDで確定。名前が同じでも別グループとは混ざりません）。'
                      : 'この領域単体の出力列名を上書きしたい場合に入力します。'}
                </p>
                {selectedFieldType === 'text_multi' && (
                  <>
                    <Label htmlFor='re-line' size='sm'>
                      行番号（1始まり）
                    </Label>
                    <input
                      id='re-line'
                      type='number'
                      min={1}
                      max={99}
                      className='w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                      value={(selected.line_index ?? 0) + 1}
                      disabled={disabled}
                      onChange={(e) =>
                        updateSelected({
                          line_index: Math.max(0, (Number(e.target.value) || 1) - 1),
                        })
                      }
                    />
                  </>
                )}
              </>
            )}
            {!selected.is_trap && isTextType(selectedFieldType) && (
              <div className='rounded-8 border border-solid-gray-420 p-2'>
                <p className='text-std-14B-150'>横に N 分割</p>
                <p className='mt-1 text-std-12N-170 text-solid-gray-700'>
                  1行の長い枠を隣同士オーバーラップ付きで分割します。
                </p>
                <div className='mt-2 grid grid-cols-2 gap-2'>
                  <div>
                    <Label htmlFor='re-split-n' size='sm'>
                      分割数 N
                    </Label>
                    <input
                      id='re-split-n'
                      type='number'
                      min={2}
                      max={20}
                      className='w-full rounded-8 border border-solid-gray-420 px-2 py-1.5'
                      value={splitN}
                      disabled={disabled}
                      onChange={(e) => setSplitN(Number(e.target.value) || DEFAULT_SPLIT_N)}
                    />
                  </div>
                  <div>
                    <Label htmlFor='re-split-ol' size='sm'>
                      隣同士 OL%
                    </Label>
                    <input
                      id='re-split-ol'
                      type='number'
                      min={0}
                      max={45}
                      className='w-full rounded-8 border border-solid-gray-420 px-2 py-1.5'
                      value={splitOverlapPct}
                      disabled={disabled}
                      onChange={(e) => setSplitOverlapPct(Number(e.target.value) || 0)}
                    />
                  </div>
                </div>
                {splitError && (
                  <p className='mt-1 text-std-12N-170 text-red-700'>{splitError}</p>
                )}
                <Button
                  type='button'
                  size='sm'
                  variant='solid-fill'
                  className='mt-2'
                  disabled={disabled}
                  onClick={splitSelectedHorizontally}
                >
                  この行を横分割
                </Button>
              </div>
            )}
            {!selected.is_trap && isChoiceType(selectedFieldType) && (
              <div className='rounded-8 border border-solid-gray-420 p-2'>
                <p className='text-std-14B-150'>選択肢</p>
                <p className='mt-1 text-std-12N-170 text-solid-gray-700'>
                  チェッカーが選ぶ選択肢です（1行に1つ）。
                  {selectedFieldType === 'choice_multi' ? '複数選択可。' : '単一選択。'}
                </p>
                <textarea
                  className='mt-2 h-28 w-full rounded-8 border border-solid-gray-420 px-3 py-2'
                  value={(selected.choice_options ?? []).join('\n')}
                  placeholder={'例:\n該当する\n該当しない'}
                  disabled={disabled}
                  onChange={(e) =>
                    updateSelected({ choice_options: e.target.value.split('\n') })
                  }
                />
              </div>
            )}
            <p className='text-std-12N-170 text-solid-gray-700'>
              座標: x={selected.x.toFixed(3)} y={selected.y.toFixed(3)} w=
              {selected.w.toFixed(3)} h={selected.h.toFixed(3)}
              {(selected.group_name || selected.group_id) &&
                ` / 片=${(selected.part_index ?? 0) + 1}`}
            </p>
            <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={removeSelected}>
              この領域を削除
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};

export const regionsFromEditor = (regions: RegionTemplate[]): RegionTemplate[] =>
  regions.map((r, i) => {
    const fieldType = normalizeFieldType(r.field_type);
    const choice = isChoiceType(fieldType)
      ? (r.choice_options ?? []).map((s) => s.trim()).filter(Boolean)
      : [];
    return {
      id: r.id,
      name: r.name,
      page_index: r.page_index ?? 0,
      x: num(r.x),
      y: num(r.y),
      w: num(r.w),
      h: num(r.h),
      field_type: fieldType,
      is_handwriting: r.is_handwriting ?? true,
      is_trap: !!r.is_trap,
      trap_answer: r.is_trap ? r.trap_answer || null : null,
      sort_order: i,
      group_id: r.group_id ?? null,
      group_name: (r.group_name ?? '').trim() || null,
      line_index: r.line_index ?? 0,
      part_index: r.part_index ?? 0,
      choice_options: choice,
    };
  });
