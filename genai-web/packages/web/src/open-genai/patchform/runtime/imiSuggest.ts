import type { FormComponent } from '../types';

export const IMI_PRESETS = [
  'ic:氏名',
  'ic:氏',
  'ic:名',
  'ic:氏読み',
  'ic:名読み',
  'ic:性別',
  'ic:住所',
  'ic:郵便番号',
  'ic:都道府県',
  'ic:市区町村',
  'ic:建物名',
  'ic:電子メール',
  'ic:電話番号',
  'ic:生年月日',
  'ic:法人番号',
  'ic:法人',
  'ic:名称',
  'ic:口座',
];

/** 部品タイプから一意に決まる語彙。カタログ追加時の初期値。 */
export const DEFAULT_IMI: Record<string, string> = {
  email: 'ic:電子メール',
  phone: 'ic:電話番号',
  address_composite: 'ic:住所',
  user_info_composite: 'ic:氏名',
  company_info_composite: 'ic:法人',
  financial_institution_composite: 'ic:口座',
};

/** 複合のサブ項目で一意に決まる語彙。 */
export const DEFAULT_IMI_SUBFIELDS: Record<string, Record<string, string>> = {
  address_composite: {
    postal_code: 'ic:郵便番号',
    prefecture: 'ic:都道府県',
    city: 'ic:市区町村',
    building: 'ic:建物名',
  },
  user_info_composite: {
    last_name: 'ic:氏',
    first_name: 'ic:名',
    last_name_kana: 'ic:氏読み',
    first_name_kana: 'ic:名読み',
    gender: 'ic:性別',
    birth_date: 'ic:生年月日',
  },
  company_info_composite: {
    company_name: 'ic:名称',
    corporate_number: 'ic:法人番号',
    representative: 'ic:氏名',
  },
};

export const COMPOSITE_SUBFIELDS: Record<string, string[]> = {
  address_composite: ['postal_code', 'prefecture', 'city', 'street', 'building'],
  user_info_composite: [
    'last_name',
    'first_name',
    'last_name_kana',
    'first_name_kana',
    'gender',
    'birth_date',
  ],
  company_info_composite: ['company_name', 'corporate_number', 'representative'],
  financial_institution_composite: [
    'is_yuucho',
    'bank_code',
    'bank_name',
    'branch_code',
    'branch_name',
    'account_type',
    'account_number',
    'yuucho_symbol',
    'yuucho_number',
    'account_holder',
  ],
};

export const COMPOSITE_SUBFIELD_LABELS: Record<string, string> = {
  postal_code: '郵便番号',
  prefecture: '都道府県',
  city: '市区町村',
  street: '町名・番地',
  building: '建物名',
  last_name: '姓',
  first_name: '名',
  last_name_kana: 'セイ',
  first_name_kana: 'メイ',
  gender: '性別',
  birth_date: '生年月日',
  company_name: '法人名',
  corporate_number: '法人番号',
  representative: '代表者',
  is_yuucho: 'ゆうちょ',
  bank_code: '金融機関コード',
  bank_name: '金融機関名',
  branch_code: '支店コード',
  branch_name: '支店名',
  account_type: '口座種別',
  account_number: '口座番号',
  yuucho_symbol: '記号',
  yuucho_number: '番号',
  account_holder: '口座名義',
};

export type SuggestSlot = { componentId: string; subkey?: string };

export type SuggestOption = { value: string; sourceLabel: string };

const asRecord = (value: unknown): Record<string, string> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(
        Object.entries(value as Record<string, unknown>).map(([k, v]) => [
          k,
          v == null ? '' : String(v),
        ]),
      )
    : {};

export const imiKey = (component: FormComponent, subkey?: string): string => {
  if (component.type === 'mynumber') return '';
  if (subkey) {
    const explicit = String(component.imi_subfields?.[subkey] || '').trim();
    if (explicit) return explicit;
    const parent = String(component.imi_type || '').trim();
    return parent ? `${parent}#${subkey}` : '';
  }
  return String(component.imi_type || '').trim();
};

const sourceLabel = (component: FormComponent, subkey?: string): string => {
  const name = component.label || component.id;
  if (!subkey) return name;
  const sub = COMPOSITE_SUBFIELD_LABELS[subkey] || subkey;
  return `${name} ${sub}`;
};

const scalarText = (value: unknown): string => {
  if (typeof value !== 'string' && typeof value !== 'number') return '';
  return String(value).trim();
};

export const suggestFor = (
  components: FormComponent[],
  answers: Record<string, unknown>,
  slot: SuggestSlot,
): SuggestOption[] => {
  const target = components.find((c) => c.id === slot.componentId);
  if (!target) return [];
  const key = imiKey(target, slot.subkey);
  if (!key) return [];

  const seen = new Set<string>();
  const out: SuggestOption[] = [];
  const push = (value: string, label: string) => {
    if (!value || seen.has(value)) return;
    seen.add(value);
    out.push({ value, sourceLabel: label });
  };

  for (const c of components) {
    const subs = COMPOSITE_SUBFIELDS[c.type];
    if (subs) {
      const rec = asRecord(answers[c.id]);
      for (const sub of subs) {
        if (c.id === slot.componentId && sub === slot.subkey) continue;
        if (imiKey(c, sub) !== key) continue;
        push(String(rec[sub] || '').trim(), sourceLabel(c, sub));
      }
      continue;
    }
    if (c.id === slot.componentId && !slot.subkey) continue;
    if (imiKey(c) !== key) continue;
    push(scalarText(answers[c.id]), sourceLabel(c));
  }
  return out;
};
