export type NormalizeKind = 'digits' | 'postal' | 'phone' | 'street' | 'numeric' | 'nfkc';

const HYPHENS = /[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043\uFE58\uFE63\uFF0D]/g;
const HYPHENS_OR_CHOON = /[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043\uFE58\uFE63\uFF0D\u30FC\uFF70]/g;

const nfkc = (value: string) => value.normalize('NFKC').trim();

const hyphens = (value: string, choon: boolean) =>
  value.replace(choon ? HYPHENS_OR_CHOON : HYPHENS, '-').replace(/-{2,}/g, '-');

export const normalizeInput = (value: string, kind: NormalizeKind): string => {
  if (kind === 'digits') return hyphens(nfkc(value), true).replace(/\D/g, '');
  if (kind === 'postal') {
    const compact = hyphens(nfkc(value), true).replace(/[^\d-]/g, '');
    const digits = compact.replace(/-/g, '');
    return /^\d{7}$/.test(digits) ? `${digits.slice(0, 3)}-${digits.slice(3)}` : compact;
  }
  if (kind === 'phone') {
    return hyphens(nfkc(value), true)
      .replace(/[^\d+\-() ]/g, '')
      .replace(/ {2,}/g, ' ')
      .trim();
  }
  if (kind === 'street') return hyphens(nfkc(value), true).replace(/ {2,}/g, ' ').trim();
  if (kind === 'numeric') return hyphens(nfkc(value), false).replace(/,/g, '');
  return nfkc(value);
};

export const COMPOSITE_NORMALIZE: Record<string, Partial<Record<string, NormalizeKind>>> = {
  address_composite: {
    postal_code: 'postal',
    prefecture: 'nfkc',
    city: 'nfkc',
    street: 'street',
    building: 'nfkc',
  },
  company_info_composite: { corporate_number: 'digits' },
  financial_institution_composite: {
    bank_code: 'digits',
    branch_code: 'digits',
    account_number: 'digits',
    yuucho_symbol: 'digits',
    yuucho_number: 'digits',
  },
};
