export type BudgetConfig = {
  enabled?: boolean;
  error?: string;
  year?: number;
  label?: string;
  basis?: string;
  source?: string;
  sourceUrl?: string;
  municipalities?: number;
};

export type BudgetRow = {
  code: string;
  name: string;
  pref: string;
  pop: number;
  revTotal: number;
  expTotal: number;
  balance: number;
  strength: number | null;
  currentRatio: number | null;
  rev: number[];
  purpose: number[];
  nature: number[];
};

export type BudgetData = {
  year: number;
  label: string;
  basis: string;
  unit: string;
  source: string;
  sourceUrl: string;
  revenue: string[];
  purpose: string[];
  nature: string[];
  rows: BudgetRow[];
};

export type BudgetView = 'purpose' | 'nature';
export type BudgetUnit = 'total' | 'per';
