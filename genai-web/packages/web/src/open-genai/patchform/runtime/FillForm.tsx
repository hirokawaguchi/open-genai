import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Checkbox } from '@/components/ui/dads/Checkbox';
import { Label } from '@/components/ui/dads/Label';
import { Radio } from '@/components/ui/dads/Radio';
import type { FormComponent, FormDefinition, UploadedFile } from '../types';
import { FilePickButton } from './FilePickButton';
import { evaluateFormula, formatCalculated } from './formula';
import { GENDERS, PREFECTURES, yuuchoToBranch } from './japan';
import { COMPOSITE_NORMALIZE, normalizeInput, type NormalizeKind } from './normalizeInput';
import { nextFilledPage, splitPages } from './pages';
import { isVisible, missingRequired } from './visibility';

export type ExtractKind = 'image' | 'document';
export type UploadKind = 'file' | 'signature';

type Props = {
  definition: FormDefinition;
  values: Record<string, unknown>;
  onChange: (id: string, value: unknown) => void;
  disabled?: boolean;
  onExtract?: (kind: ExtractKind, file: File) => Promise<{ extracted: string }>;
  onUpload?: (file: File, kind: UploadKind) => Promise<UploadedFile>;
  onPostalLookup?: (zip: string) => Promise<{ prefecture?: string; city?: string; street?: string } | null>;
  onCorporateLookup?: (number: string) => Promise<{ company_name?: string } | null>;
  wizard?: boolean;
  onWizardChange?: (info: { page: number; total: number; isLast: boolean }) => void;
};

const optionsOf = (c: FormComponent): string[] => {
  const raw = c.properties?.options ?? [];
  return raw.map((o) => String(o));
};

const blurNorm = (kind: NormalizeKind, current: string, apply: (next: string) => void) => {
  const next = normalizeInput(current, kind);
  if (next !== current) apply(next);
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

const fileMeta = (value: unknown): { filename: string } => {
  if (typeof value === 'string') return { filename: value };
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const rec = value as { filename?: string };
    return { filename: String(rec.filename || '') };
  }
  return { filename: '' };
};

const Field = ({
  component: c,
  value,
  onChange,
  disabled,
  onExtract,
  onUpload,
  onPostalLookup,
  onCorporateLookup,
}: {
  component: FormComponent;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
  onExtract?: (kind: ExtractKind, file: File) => Promise<{ extracted: string }>;
  onUpload?: (file: File, kind: UploadKind) => Promise<UploadedFile>;
  onPostalLookup?: (zip: string) => Promise<{ prefecture?: string; city?: string; street?: string } | null>;
  onCorporateLookup?: (number: string) => Promise<{ company_name?: string } | null>;
}) => {
  const id = `pf-${c.id}`;
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const common = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';
  const pickUpload = async (file: File | null, kind: UploadKind) => {
    if (!file) {
      setUploadError(null);
      onChange('');
      return;
    }
    if (!onUpload) {
      onChange(kind === 'signature' ? '' : { filename: file.name });
      if (kind === 'signature') {
        const reader = new FileReader();
        reader.onload = () => onChange(String(reader.result || ''));
        reader.readAsDataURL(file);
      }
      return;
    }
    setUploadBusy(true);
    setUploadError(null);
    try {
      onChange(await onUpload(file, kind));
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'アップロードに失敗しました');
      onChange('');
    } finally {
      setUploadBusy(false);
    }
  };
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
                onBlur={(e) =>
                  blurNorm('digits', e.target.value, (v) => {
                    const conv = yuuchoToBranch(v, obj.yuucho_number ?? '');
                    set({ yuucho_symbol: v, ...conv });
                  })
                }
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
                onBlur={(e) =>
                  blurNorm('digits', e.target.value, (v) => {
                    const conv = yuuchoToBranch(obj.yuucho_symbol ?? '', v);
                    set({ yuucho_number: v, ...conv });
                  })
                }
              />
            </div>
            {obj.branch_code ? (
              <p className='md:col-span-2 text-dns-14N-130 text-solid-gray-700'>
                店番 {obj.branch_code}
                {obj.account_number ? ` / 口座番号 ${obj.account_number}` : ''}
                （記号・番号から換算）
              </p>
            ) : null}
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
  if (c.type === 'address_composite') {
    const obj = asRecord(value);
    const set = (patch: Record<string, string>) => onChange({ ...obj, ...patch });
    const runPostal = async (raw: string) => {
      const zip = normalizeInput(raw, 'postal');
      set({ postal_code: zip });
      if (!onPostalLookup || zip.replace(/\D/g, '').length !== 7) return;
      setLookupBusy(true);
      setLookupError(null);
      try {
        const found = await onPostalLookup(zip);
        if (!found) {
          setLookupError('該当する住所が見つかりません');
          return;
        }
        set({
          postal_code: zip,
          prefecture: found.prefecture || obj.prefecture,
          city: found.city || obj.city,
          street: found.street || obj.street,
        });
      } catch (e) {
        setLookupError(e instanceof Error ? e.message : '住所の検索に失敗しました');
      } finally {
        setLookupBusy(false);
      }
    };
    return (
      <div className='mt-1 grid gap-2 md:grid-cols-2'>
        <div className='md:col-span-2'>
          <Label htmlFor={`${id}-postal_code`} size='sm'>
            郵便番号
          </Label>
          <div className='flex flex-wrap items-end gap-2'>
            <input
              id={`${id}-postal_code`}
              className={`${common} max-w-40`}
              inputMode='numeric'
              placeholder='123-4567'
              value={obj.postal_code ?? ''}
              disabled={disabled}
              onChange={(e) => set({ postal_code: e.target.value })}
              onBlur={(e) => void runPostal(e.target.value)}
            />
            {onPostalLookup ? (
              <button
                type='button'
                className='mb-0.5 text-std-16N-170 text-blue-900 underline'
                disabled={disabled || lookupBusy}
                onClick={() => void runPostal(obj.postal_code ?? '')}
              >
                {lookupBusy ? '検索中...' : '住所を検索'}
              </button>
            ) : null}
          </div>
          {lookupError ? (
            <p className='mt-1 text-dns-14N-130 text-error-1' role='alert'>
              {lookupError}
            </p>
          ) : null}
        </div>
        <div>
          <Label htmlFor={`${id}-prefecture`} size='sm'>
            都道府県
          </Label>
          <select
            id={`${id}-prefecture`}
            className={common}
            value={obj.prefecture ?? ''}
            disabled={disabled}
            onChange={(e) => set({ prefecture: e.target.value })}
          >
            <option value=''>選択してください</option>
            {PREFECTURES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor={`${id}-city`} size='sm'>
            市区町村
          </Label>
          <input
            id={`${id}-city`}
            className={common}
            value={obj.city ?? ''}
            disabled={disabled}
            onChange={(e) => set({ city: e.target.value })}
            onBlur={(e) => blurNorm('nfkc', e.target.value, (v) => set({ city: v }))}
          />
        </div>
        <div className='md:col-span-2'>
          <Label htmlFor={`${id}-street`} size='sm'>
            町名・番地
          </Label>
          <input
            id={`${id}-street`}
            className={common}
            value={obj.street ?? ''}
            disabled={disabled}
            onChange={(e) => set({ street: e.target.value })}
            onBlur={(e) => blurNorm('street', e.target.value, (v) => set({ street: v }))}
          />
        </div>
        <div className='md:col-span-2'>
          <Label htmlFor={`${id}-building`} size='sm'>
            建物名
          </Label>
          <input
            id={`${id}-building`}
            className={common}
            value={obj.building ?? ''}
            disabled={disabled}
            onChange={(e) => set({ building: e.target.value })}
            onBlur={(e) => blurNorm('nfkc', e.target.value, (v) => set({ building: v }))}
          />
        </div>
      </div>
    );
  }
  if (c.type === 'user_info_composite') {
    const obj = asRecord(value);
    const set = (patch: Record<string, string>) => onChange({ ...obj, ...patch });
    return (
      <div className='mt-1 grid gap-2 md:grid-cols-2'>
        <div>
          <Label htmlFor={`${id}-last_name`} size='sm'>
            姓
          </Label>
          <input
            id={`${id}-last_name`}
            className={common}
            value={obj.last_name ?? ''}
            disabled={disabled}
            onChange={(e) => set({ last_name: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor={`${id}-first_name`} size='sm'>
            名
          </Label>
          <input
            id={`${id}-first_name`}
            className={common}
            value={obj.first_name ?? ''}
            disabled={disabled}
            onChange={(e) => set({ first_name: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor={`${id}-last_name_kana`} size='sm'>
            セイ
          </Label>
          <input
            id={`${id}-last_name_kana`}
            className={common}
            value={obj.last_name_kana ?? ''}
            disabled={disabled}
            onChange={(e) => set({ last_name_kana: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor={`${id}-first_name_kana`} size='sm'>
            メイ
          </Label>
          <input
            id={`${id}-first_name_kana`}
            className={common}
            value={obj.first_name_kana ?? ''}
            disabled={disabled}
            onChange={(e) => set({ first_name_kana: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor={`${id}-gender`} size='sm'>
            性別
          </Label>
          <select
            id={`${id}-gender`}
            className={common}
            value={obj.gender ?? ''}
            disabled={disabled}
            onChange={(e) => set({ gender: e.target.value })}
          >
            <option value=''>選択してください</option>
            {GENDERS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor={`${id}-birth_date`} size='sm'>
            生年月日
          </Label>
          <input
            id={`${id}-birth_date`}
            type='date'
            className={common}
            value={obj.birth_date ?? ''}
            disabled={disabled}
            onChange={(e) => set({ birth_date: e.target.value })}
          />
        </div>
      </div>
    );
  }
  if (c.type === 'company_info_composite') {
    const obj = asRecord(value);
    const set = (patch: Record<string, string>) => onChange({ ...obj, ...patch });
    const runCorporate = async (raw: string) => {
      const number = normalizeInput(raw, 'digits');
      set({ corporate_number: number });
      if (!onCorporateLookup || number.length !== 13) return;
      setLookupBusy(true);
      setLookupError(null);
      try {
        const found = await onCorporateLookup(number);
        if (!found?.company_name) {
          setLookupError('法人名を自動入力できませんでした。手入力してください。');
          return;
        }
        set({ corporate_number: number, company_name: found.company_name });
      } catch (e) {
        setLookupError(e instanceof Error ? e.message : '法人番号の検索に失敗しました');
      } finally {
        setLookupBusy(false);
      }
    };
    return (
      <div className='mt-1 grid gap-2 md:grid-cols-2'>
        <div className='md:col-span-2'>
          <Label htmlFor={`${id}-corporate_number`} size='sm'>
            法人番号
          </Label>
          <div className='flex flex-wrap items-end gap-2'>
            <input
              id={`${id}-corporate_number`}
              className={`${common} max-w-56`}
              inputMode='numeric'
              maxLength={13}
              placeholder='13桁'
              value={obj.corporate_number ?? ''}
              disabled={disabled}
              onChange={(e) => set({ corporate_number: e.target.value })}
              onBlur={(e) => void runCorporate(e.target.value)}
            />
            {onCorporateLookup ? (
              <button
                type='button'
                className='mb-0.5 text-std-16N-170 text-blue-900 underline'
                disabled={disabled || lookupBusy}
                onClick={() => void runCorporate(obj.corporate_number ?? '')}
              >
                {lookupBusy ? '検索中...' : '法人名を検索'}
              </button>
            ) : null}
          </div>
          {lookupError ? (
            <p className='mt-1 text-dns-14N-130 text-error-1' role='alert'>
              {lookupError}
            </p>
          ) : null}
        </div>
        <div>
          <Label htmlFor={`${id}-company_name`} size='sm'>
            法人名
          </Label>
          <input
            id={`${id}-company_name`}
            className={common}
            value={obj.company_name ?? ''}
            disabled={disabled}
            onChange={(e) => set({ company_name: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor={`${id}-representative`} size='sm'>
            代表者
          </Label>
          <input
            id={`${id}-representative`}
            className={common}
            value={obj.representative ?? ''}
            disabled={disabled}
            onChange={(e) => set({ representative: e.target.value })}
          />
        </div>
      </div>
    );
  }
  if (c.type === 'calculated') {
    return (
      <p id={id} className='mt-1 text-std-16N-170 text-solid-gray-800'>
        {formatCalculated(value)}
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
    const picked = fileMeta(value).filename || (typeof value === 'string' && value ? '選択済み' : '');
    return (
      <FilePickButton
        id={id}
        accept='image/*'
        disabled={disabled}
        busy={uploadBusy}
        error={uploadError}
        buttonLabel='署名画像を選択'
        filename={picked}
        onFile={(file) => void pickUpload(file, 'signature')}
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
        busy={uploadBusy}
        error={uploadError}
        filename={fileMeta(value).filename}
        onFile={(file) => void pickUpload(file, 'file')}
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
export const FillForm = ({
  definition,
  values,
  onChange,
  disabled,
  onExtract,
  onUpload,
  onPostalLookup,
  onCorporateLookup,
  wizard = true,
  onWizardChange,
}: Props) => {
  const pages = useMemo(() => splitPages(definition.components), [definition.components]);
  const useWizard = wizard && pages.length > 1;
  const [page, setPage] = useState(0);
  const [pageError, setPageError] = useState<string | null>(null);
  const shape = definition.components.map((c) => c.id).join(',');

  useEffect(() => {
    setPage(0);
    setPageError(null);
  }, [shape]);

  useEffect(() => {
    const next = { ...values };
    for (const c of definition.components) {
      if (c.type !== 'calculated' || !isVisible(c, next)) continue;
      const result = evaluateFormula(String(c.properties?.formula || ''), next);
      if (result != null) next[c.id] = result;
      if (result == null) {
        if (values[c.id] != null) onChange(c.id, null);
        continue;
      }
      if (values[c.id] !== result) onChange(c.id, result);
    }
  }, [definition.components, onChange, values]);

  const safePage = Math.min(page, Math.max(pages.length - 1, 0));
  const current = (useWizard ? pages[safePage] : definition.components) ?? [];
  const shown = useWizard ? current : definition.components;
  const total = pages.length;
  const isLast = !useWizard || safePage >= total - 1;

  useEffect(() => {
    onWizardChange?.({ page: safePage, total: useWizard ? total : 1, isLast });
  }, [isLast, onWizardChange, safePage, total, useWizard]);

  const go = (direction: 1 | -1) => {
    if (direction === 1) {
      const missing = missingRequired(current, values);
      if (missing) {
        setPageError(`${missing.label}は必須です`);
        return;
      }
    }
    setPageError(null);
    setPage((p) =>
      nextFilledPage(pages, p, direction, (items) => items.some((c) => isVisible(c, values))),
    );
  };

  return (
    <div className='flex flex-col gap-4'>
      {useWizard ? (
        <div>
          <p className='text-dns-14N-130 text-solid-gray-700'>
            ページ {safePage + 1} / {total}
          </p>
          <div className='mt-2 h-2 overflow-hidden rounded-full bg-solid-gray-200'>
            <div
              className='h-full bg-blue-900'
              style={{ width: `${Math.round(((safePage + 1) / total) * 100)}%` }}
            />
          </div>
        </div>
      ) : null}
      {shown.map((c) => {
        if (c.type === 'page_break') return null;
        if (!isVisible(c, values)) return null;
        const hideLabel = !!c.hide_label;
        const skipHeading = c.type === 'divider';
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
              onUpload={onUpload}
              onPostalLookup={onPostalLookup}
              onCorporateLookup={onCorporateLookup}
            />
          </div>
        );
      })}
      {useWizard ? (
        <div className='flex flex-col gap-2'>
          {pageError ? (
            <p className='text-dns-14N-130 text-error-1' role='alert'>
              {pageError}
            </p>
          ) : null}
          <div className='flex flex-wrap gap-2'>
            {safePage > 0 ? (
              <Button type='button' variant='outline' size='md' onClick={() => go(-1)}>
                前へ
              </Button>
            ) : null}
            {!isLast ? (
              <Button type='button' variant='solid-fill' size='md' onClick={() => go(1)}>
                次へ
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};
