import { Checkbox } from '@/components/ui/dads/Checkbox';
import { Label } from '@/components/ui/dads/Label';
import { Radio } from '@/components/ui/dads/Radio';
import type { FormComponent, FormDefinition } from '../types';
import { FilePickButton } from './FilePickButton';
import { COMPOSITE_NORMALIZE, normalizeInput, type NormalizeKind } from './normalizeInput';

export type ExtractKind = 'image' | 'document';

type Props = {
  definition: FormDefinition;
  values: Record<string, unknown>;
  onChange: (id: string, value: unknown) => void;
  disabled?: boolean;
  onExtract?: (kind: ExtractKind, file: File) => Promise<{ extracted: string }>;
};

const optionsOf = (c: FormComponent): string[] => {
  const raw = c.properties?.options ?? [];
  return raw.map((o) => String(o));
};

const isVisible = (c: FormComponent, values: Record<string, unknown>): boolean => {
  const cond = c.visibleWhen;
  if (!cond) return true;
  const rules = Array.isArray(cond) ? cond : [cond];
  return rules.every((rule) => {
    const value = values[rule.field];
    if (rule.eq !== undefined && value !== rule.eq) return false;
    if (rule.in && !rule.in.includes(String(value ?? ''))) return false;
    return true;
  });
};

const blurNorm = (kind: NormalizeKind, current: string, apply: (next: string) => void) => {
  const next = normalizeInput(current, kind);
  if (next !== current) apply(next);
};

const COMPOSITE_FIELDS: Record<string, Array<{ key: string; label: string }>> = {
  address_composite: [
    { key: 'postal_code', label: '郵便番号' },
    { key: 'prefecture', label: '都道府県' },
    { key: 'city', label: '市区町村' },
    { key: 'street', label: '町名・番地' },
    { key: 'building', label: '建物名' },
  ],
  user_info_composite: [
    { key: 'last_name', label: '姓' },
    { key: 'first_name', label: '名' },
    { key: 'last_name_kana', label: 'セイ' },
    { key: 'first_name_kana', label: 'メイ' },
  ],
  company_info_composite: [
    { key: 'company_name', label: '法人名' },
    { key: 'corporate_number', label: '法人番号' },
    { key: 'representative', label: '代表者' },
  ],
};

const ACCOUNT_TYPES = ['普通', '当座', '貯蓄'];

const isYuucho = (obj: Record<string, string>): boolean =>
  obj.is_yuucho === '1' || obj.is_yuucho === 'true' || obj.is_yuucho === 'yes';

const asRecord = (value: unknown): Record<string, string> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, v == null ? '' : String(v)]))
    : {};

const safeImageSrc = (src: string): string =>
  src.startsWith('https://') || src.startsWith('http://') || src.startsWith('data:image/') ? src : '';

const Field = ({
  component: c,
  value,
  onChange,
  disabled,
  onExtract,
}: {
  component: FormComponent;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  onExtract?: (kind: ExtractKind, file: File) => Promise<{ extracted: string }>;
}) => {
  const id = `pf-${c.id}`;
  const common = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';
  if (c.type === 'financial_institution_composite') {
    const obj = asRecord(value);
    const yuucho = isYuucho(obj);
    const set = (patch: Record<string, string>) => onChange({ ...obj, ...patch });
    return (
      <div className='mt-1 flex flex-col gap-3'>
        <Checkbox
          size='md'
          checked={yuucho}
          disabled={disabled}
          onChange={(e) =>
            set(
              e.target.checked
                ? { is_yuucho: '1', bank_name: obj.bank_name || 'ゆうちょ銀行', bank_code: obj.bank_code || '9900' }
                : { is_yuucho: '' },
            )
          }
        >
          ゆうちょ銀行の場合
        </Checkbox>
        {yuucho ? (
          <div className='grid gap-2 md:grid-cols-2'>
            <div>
              <Label htmlFor={`${id}-yuucho_symbol`} size='sm'>
                記号
              </Label>
              <input
                id={`${id}-yuucho_symbol`}
                className={common}
                inputMode='numeric'
                maxLength={5}
                placeholder='5桁'
                value={obj.yuucho_symbol ?? ''}
                disabled={disabled}
                onChange={(e) => set({ yuucho_symbol: e.target.value })}
                onBlur={(e) => blurNorm('digits', e.target.value, (v) => set({ yuucho_symbol: v }))}
              />
            </div>
            <div>
              <Label htmlFor={`${id}-yuucho_number`} size='sm'>
                番号
              </Label>
              <input
                id={`${id}-yuucho_number`}
                className={common}
                inputMode='numeric'
                maxLength={8}
                placeholder='8桁以内'
                value={obj.yuucho_number ?? ''}
                disabled={disabled}
                onChange={(e) => set({ yuucho_number: e.target.value })}
                onBlur={(e) => blurNorm('digits', e.target.value, (v) => set({ yuucho_number: v }))}
              />
            </div>
            <div className='md:col-span-2'>
              <Label htmlFor={`${id}-account_holder`} size='sm'>
                口座名義
              </Label>
              <input
                id={`${id}-account_holder`}
                className={common}
                value={obj.account_holder ?? ''}
                disabled={disabled}
                onChange={(e) => set({ account_holder: e.target.value })}
              />
            </div>
          </div>
        ) : (
          <div className='grid gap-2 md:grid-cols-2'>
            <div>
              <Label htmlFor={`${id}-bank_code`} size='sm'>
                金融機関コード
              </Label>
              <input
                id={`${id}-bank_code`}
                className={common}
                inputMode='numeric'
                maxLength={4}
                placeholder='4桁'
                value={obj.bank_code ?? ''}
                disabled={disabled}
                onChange={(e) => set({ bank_code: e.target.value })}
                onBlur={(e) => blurNorm('digits', e.target.value, (v) => set({ bank_code: v }))}
              />
            </div>
            <div>
              <Label htmlFor={`${id}-bank_name`} size='sm'>
                金融機関名
              </Label>
              <input
                id={`${id}-bank_name`}
                className={common}
                value={obj.bank_name ?? ''}
                disabled={disabled}
                onChange={(e) => set({ bank_name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor={`${id}-branch_code`} size='sm'>
                支店コード
              </Label>
              <input
                id={`${id}-branch_code`}
                className={common}
                inputMode='numeric'
                maxLength={3}
                placeholder='3桁'
                value={obj.branch_code ?? ''}
                disabled={disabled}
                onChange={(e) => set({ branch_code: e.target.value })}
                onBlur={(e) => blurNorm('digits', e.target.value, (v) => set({ branch_code: v }))}
              />
            </div>
            <div>
              <Label htmlFor={`${id}-branch_name`} size='sm'>
                支店名
              </Label>
              <input
                id={`${id}-branch_name`}
                className={common}
                value={obj.branch_name ?? ''}
                disabled={disabled}
                onChange={(e) => set({ branch_name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor={`${id}-account_type`} size='sm'>
                口座種別
              </Label>
              <select
                id={`${id}-account_type`}
                className={common}
                value={obj.account_type ?? ''}
                disabled={disabled}
                onChange={(e) => set({ account_type: e.target.value })}
              >
                <option value=''>選択してください</option>
                {ACCOUNT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor={`${id}-account_number`} size='sm'>
                口座番号
              </Label>
              <input
                id={`${id}-account_number`}
                className={common}
                inputMode='numeric'
                value={obj.account_number ?? ''}
                disabled={disabled}
                onChange={(e) => set({ account_number: e.target.value })}
                onBlur={(e) => blurNorm('digits', e.target.value, (v) => set({ account_number: v }))}
              />
            </div>
            <div className='md:col-span-2'>
              <Label htmlFor={`${id}-account_holder`} size='sm'>
                口座名義
              </Label>
              <input
                id={`${id}-account_holder`}
                className={common}
                value={obj.account_holder ?? ''}
                disabled={disabled}
                onChange={(e) => set({ account_holder: e.target.value })}
              />
            </div>
          </div>
        )}
      </div>
    );
  }
  const sub = COMPOSITE_FIELDS[c.type];
  if (sub) {
    const obj = value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, string>) : {};
    return (
      <div className='mt-1 grid gap-2 md:grid-cols-2'>
        {sub.map((f) => (
          <div key={f.key}>
            <Label htmlFor={`${id}-${f.key}`} size='sm'>
              {f.label}
            </Label>
            <input
              id={`${id}-${f.key}`}
              className={common}
              inputMode={
                f.key === 'postal_code' || f.key === 'corporate_number' ? 'numeric' : undefined
              }
              value={obj[f.key] ?? ''}
              disabled={disabled}
              onChange={(e) => onChange({ ...obj, [f.key]: e.target.value })}
              onBlur={(e) => {
                const kind = COMPOSITE_NORMALIZE[c.type]?.[f.key];
                if (!kind) return;
                blurNorm(kind, e.target.value, (v) => onChange({ ...obj, [f.key]: v }));
              }}
            />
          </div>
        ))}
      </div>
    );
  }
  if (c.type === 'calculated') {
    return (
      <p id={id} className='mt-1 text-std-16N-170 text-solid-gray-700'>
        送信時に自動計算されます
      </p>
    );
  }
  if (c.type === 'text_display') {
    return <p className='mt-1 text-std-16N-170 text-solid-gray-700'>{String(c.properties?.text || c.label)}</p>;
  }
  if (c.type === 'image_display') {
    const src = safeImageSrc(String(c.properties?.src || ''));
    if (!src) return <p className='mt-1 text-dns-14N-130 text-solid-gray-700'>画像 URL が未設定です</p>;
    return <img src={src} alt={c.label} className='mt-1 max-h-64 max-w-full rounded-4 border border-solid-gray-300' />;
  }
  if (c.type === 'divider' || c.type === 'page_break') {
    return <hr className='my-2 border-solid-gray-300' />;
  }
  if (c.type === 'location') {
    const obj = value && typeof value === 'object' && !Array.isArray(value) ? (value as { lat?: number | string; lng?: number | string }) : {};
    return (
      <div className='mt-1 grid gap-2 md:grid-cols-3'>
        <button
          type='button'
          className='rounded-4 border border-solid-gray-420 px-3 py-2 text-dns-16N-130'
          disabled={disabled}
          onClick={() => {
            if (!navigator.geolocation) return;
            navigator.geolocation.getCurrentPosition((pos) =>
              onChange({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
            );
          }}
        >
          現在地を取得
        </button>
        <input
          className={common}
          inputMode='decimal'
          placeholder='緯度'
          value={obj.lat ?? ''}
          disabled={disabled}
          onChange={(e) => onChange({ ...obj, lat: e.target.value })}
        />
        <input
          className={common}
          inputMode='decimal'
          placeholder='経度'
          value={obj.lng ?? ''}
          disabled={disabled}
          onChange={(e) => onChange({ ...obj, lng: e.target.value })}
        />
      </div>
    );
  }
  if (c.type === 'qr_scanner') {
    return (
      <div className='mt-1 flex flex-col gap-2'>
        <input
          id={id}
          className={common}
          value={typeof value === 'string' ? value : ''}
          placeholder={c.placeholder || '読み取った内容'}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        />
        <FilePickButton
          accept='image/*'
          disabled={disabled}
          buttonLabel='QR画像を選択'
          onFile={async (file) => {
            if (!file || !('BarcodeDetector' in window)) return;
            try {
              const Detector = (window as unknown as { BarcodeDetector: new (opts: { formats: string[] }) => { detect: (src: ImageBitmap) => Promise<Array<{ rawValue: string }>> } }).BarcodeDetector;
              const detector = new Detector({ formats: ['qr_code'] });
              const bmp = await createImageBitmap(file);
              const codes = await detector.detect(bmp);
              if (codes[0]?.rawValue) onChange(codes[0].rawValue);
            } catch {
              /* 手入力にフォールバック */
            }
          }}
        />
      </div>
    );
  }
  if (c.type === 'image_recognition' || c.type === 'document_reader') {
    const obj = value && typeof value === 'object' && !Array.isArray(value) ? (value as { filename?: string; extracted?: string }) : {};
    return (
      <div className='mt-1 flex flex-col gap-2'>
        <FilePickButton
          id={id}
          accept={c.type === 'image_recognition' ? 'image/*' : undefined}
          disabled={disabled}
          filename={obj.filename}
          onFile={async (file) => {
            if (!file) {
              onChange({});
              return;
            }
            onChange({ filename: file.name, extracted: obj.extracted || '' });
            if (!onExtract) return;
            try {
              const res = await onExtract(c.type === 'image_recognition' ? 'image' : 'document', file);
              onChange({ filename: file.name, extracted: res.extracted || '' });
            } catch {
              onChange({ filename: file.name, extracted: obj.extracted || '' });
            }
          }}
        />
        <textarea
          className={common}
          rows={4}
          placeholder='読み取った内容（自動読取できない場合は手入力）'
          value={obj.extracted || ''}
          disabled={disabled}
          onChange={(e) => onChange({ ...obj, extracted: e.target.value })}
        />
      </div>
    );
  }
  if (c.type === 'daterange') {
    const obj = value && typeof value === 'object' ? (value as { start?: string; end?: string }) : {};
    return (
      <div className='mt-1 grid gap-2 md:grid-cols-2'>
        <input type='date' className={common} value={obj.start ?? ''} disabled={disabled} onChange={(e) => onChange({ ...obj, start: e.target.value })} />
        <input type='date' className={common} value={obj.end ?? ''} disabled={disabled} onChange={(e) => onChange({ ...obj, end: e.target.value })} />
      </div>
    );
  }
  if (c.type === 'slider') {
    return (
      <input
        id={id}
        type='range'
        min={0}
        max={100}
        className='mt-2 w-full'
        value={value == null ? 50 : Number(value)}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    );
  }
  if (c.type === 'rating') {
    return (
      <div className='mt-1 flex gap-2'>
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className='text-std-16N-170'>
            <input
              type='radio'
              name={c.id}
              checked={Number(value) === n}
              disabled={disabled}
              onChange={() => onChange(n)}
            />{' '}
            {n}
          </label>
        ))}
      </div>
    );
  }
  if (c.type === 'matrix_question') {
    const rows = ((c.properties?.rows as string[]) || []).map(String);
    const cols = ((c.properties?.columns as string[]) || []).map(String);
    const obj = value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, string>) : {};
    return (
      <div className='mt-2 overflow-x-auto'>
        <table className='text-dns-14N-130'>
          <thead>
            <tr>
              <th />
              {cols.map((col) => (
                <th key={col} className='px-2'>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                <td className='pr-2'>{row}</td>
                {cols.map((col) => (
                  <td key={col} className='text-center'>
                    <input
                      type='radio'
                      name={`${c.id}-${row}`}
                      checked={obj[row] === col}
                      disabled={disabled}
                      onChange={() => onChange({ ...obj, [row]: col })}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (c.type === 'signature_pad') {
    return (
      <FilePickButton
        id={id}
        accept='image/*'
        disabled={disabled}
        buttonLabel='署名画像を選択'
        filename={typeof value === 'string' && value ? '選択済み' : ''}
        onFile={(file) => {
          if (!file) {
            onChange('');
            return;
          }
          const reader = new FileReader();
          reader.onload = () => onChange(String(reader.result || ''));
          reader.readAsDataURL(file);
        }}
      />
    );
  }
  if (c.type === 'textarea') {
    return (
      <textarea
        id={id}
        className={common}
        rows={4}
        value={typeof value === 'string' ? value : ''}
        placeholder={c.placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  if (c.type === 'select') {
    return (
      <select
        id={id}
        className={common}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value=''>選択してください</option>
        {optionsOf(c).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }
  if (c.type === 'radio') {
    return (
      <div className='mt-1 flex flex-col'>
        {optionsOf(c).map((o) => (
          <Radio
            key={o}
            size='md'
            name={c.id}
            value={o}
            checked={value === o}
            disabled={disabled}
            onChange={() => onChange(o)}
          >
            {o}
          </Radio>
        ))}
      </div>
    );
  }
  if (c.type === 'checkbox') {
    const selected = Array.isArray(value) ? value.map(String) : [];
    return (
      <div className='mt-1 flex flex-col'>
        {optionsOf(c).map((o) => (
          <Checkbox
            key={o}
            size='md'
            value={o}
            checked={selected.includes(o)}
            disabled={disabled}
            onChange={() =>
              onChange(selected.includes(o) ? selected.filter((x) => x !== o) : [...selected, o])
            }
          >
            {o}
          </Checkbox>
        ))}
      </div>
    );
  }
  const inputType =
    c.type === 'email'
      ? 'email'
      : c.type === 'phone'
        ? 'tel'
        : c.type === 'number'
          ? 'number'
          : c.type === 'date'
            ? 'date'
            : c.type === 'time'
              ? 'time'
              : c.type === 'datetime-local'
                ? 'datetime-local'
                : c.type === 'password'
                  ? 'password'
                  : c.type === 'mynumber'
                    ? 'text'
                    : c.type === 'file'
                      ? 'file'
                      : 'text';
  if (inputType === 'file') {
    return (
      <FilePickButton
        id={id}
        disabled={disabled}
        filename={typeof value === 'string' ? value : ''}
        onFile={(file) => onChange(file?.name ?? '')}
      />
    );
  }
  return (
    <input
      id={id}
      type={inputType}
      className={common}
      value={value == null ? '' : String(value)}
      placeholder={c.placeholder || (c.type === 'mynumber' ? '12桁' : undefined)}
      inputMode={c.type === 'mynumber' ? 'numeric' : undefined}
      maxLength={c.type === 'mynumber' ? 12 : undefined}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      onBlur={(e) => {
        const kind: NormalizeKind | null =
          c.type === 'phone'
            ? 'phone'
            : c.type === 'mynumber'
              ? 'digits'
              : c.type === 'number'
                ? 'numeric'
                : c.type === 'email'
                  ? 'nfkc'
                  : null;
        if (!kind) return;
        blurNorm(kind, e.target.value, onChange);
      }}
    />
  );
};

/** 庁内プレビュー / 記入。ゲスト UI と同じ type だけを描画する。 */
export const FillForm = ({ definition, values, onChange, disabled, onExtract }: Props) => {
  return (
    <div className='flex flex-col gap-4'>
      {definition.components.map((c) => {
        if (!isVisible(c, values)) return null;
        const hideLabel = !!c.hide_label;
        const skipHeading = c.type === 'divider' || c.type === 'page_break';
        return (
          <div key={c.id}>
            {skipHeading ? null : hideLabel ? (
              <>
                <Label htmlFor={`pf-${c.id}`} size='sm' className='sr-only'>
                  {c.label}
                  {c.required ? ' 必須' : ''}
                </Label>
                {c.required ? <p className='text-dns-14N-130 text-error-1'>必須</p> : null}
              </>
            ) : (
              <Label htmlFor={`pf-${c.id}`} size='sm'>
                {c.label}
                {c.required ? <span className='ml-1 text-error-1'>必須</span> : null}
              </Label>
            )}
            <Field
              component={c}
              value={values[c.id]}
              onChange={(v) => onChange(c.id, v)}
              disabled={disabled}
              onExtract={onExtract}
            />
          </div>
        );
      })}
    </div>
  );
};
